#!/usr/bin/env bash
set -uo pipefail

# 未传命令行参数时处理的默认 NVMe 控制器列表，设备之间使用空格分隔。
DEFAULT_DEVICES="${DEFAULT_DEVICES:-/dev/nvme1}"
# CSD Flash 写命令 opcode，对应驱动中的 UPDATE_CSD_NOR_OP。
FLASH_WRITE_OPCODE="${FLASH_WRITE_OPCODE:-0xD1}"
# CSD Cache clear 命令 opcode。
CACHE_CLEAR_OPCODE="${CACHE_CLEAR_OPCODE:-0xD8}"
# CSD Flash 读命令 opcode，对应驱动中的 LOAD_CSD_NOR_OP。
FLASH_READ_OPCODE="${FLASH_READ_OPCODE:-0xDE}"
# CSD Flash 硬件传输长度。新固件默认使用完整 8 KiB；旧固件可显式设为 4096。
FLASH_SIZE="${DRAID_CSD_FLASH_SIZE:-8192}"
# CSD Flash 命令的 CDW10，以 dword 为单位表示固定传输长度。
FLASH_CDW10=$((FLASH_SIZE / 4))
# NVMe admin 命令使用的 namespace ID，控制器级命令固定为 0。
NAMESPACE_ID="${NAMESPACE_ID:-0}"
# 临时文件根目录，用于保存全零输入和逐卡回读数据。
TEMP_ROOT="${TMPDIR:-/tmp}"

FAILED_DEVICES=()
TEMP_DIR=""
ZERO_FILE=""

print_cmd() {
    printf '+ '
    printf '%q ' "$@"
    printf '\n'
}

run_cmd() {
    print_cmd "$@"
    "$@"
}

cleanup() {
    if [ -n "$TEMP_DIR" ] && [ -d "$TEMP_DIR" ]; then
        run_cmd rm -rf -- "$TEMP_DIR"
    fi
}
trap cleanup EXIT

usage() {
    echo "用法：sudo $0 [/dev/nvmeX ...]"
    echo
    echo "示例："
    echo "  sudo $0 /dev/nvme1 /dev/nvme2"
    echo "  sudo DEFAULT_DEVICES='/dev/nvme1 /dev/nvme2' $0"
    echo
    echo "警告：该操作会永久清空指定 CSD 的 ${FLASH_SIZE}B Flash。"
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
    usage
    exit 0
fi

if [ "$(id -u)" -ne 0 ]; then
    echo "错误：必须使用 root 权限执行。" >&2
    exit 1
fi

if ! command -v nvme >/dev/null 2>&1; then
    echo "错误：未找到 nvme 命令，请先安装 nvme-cli。" >&2
    exit 1
fi
if ! [[ "$FLASH_SIZE" =~ ^[0-9]+$ ]] || (( FLASH_SIZE % 4 != 0 )); then
    echo "错误：DRAID_CSD_FLASH_SIZE 必须是 4 字节对齐的整数：$FLASH_SIZE" >&2
    exit 1
fi
if [[ "$FLASH_SIZE" != "4096" && "$FLASH_SIZE" != "8192" ]]; then
    echo "错误：DRAID_CSD_FLASH_SIZE 只支持 4096 或 8192：$FLASH_SIZE" >&2
    exit 1
fi

# 命令行设备列表优先；未传参数时使用脚本开头的默认设备列表。
if [ "$#" -gt 0 ]; then
    DEVICES=("$@")
else
    read -r -a DEVICES <<< "$DEFAULT_DEVICES"
fi

if [ "${#DEVICES[@]}" -eq 0 ]; then
    echo "错误：没有指定 NVMe 控制器。" >&2
    usage
    exit 1
fi

for dev in "${DEVICES[@]}"; do
    if [ ! -c "$dev" ]; then
        echo "错误：NVMe 控制器节点不存在或不是字符设备：$dev" >&2
        exit 1
    fi
done

echo "即将永久清空以下 CSD Flash："
printf '  %s\n' "${DEVICES[@]}"
echo "Flash profile: ${FLASH_SIZE}B, cdw10=${FLASH_CDW10}"
printf '请输入 CLEAR 确认：'
read -r CONFIRM
if [ "$CONFIRM" != "CLEAR" ]; then
    echo "确认不匹配，已取消。"
    exit 1
fi

print_cmd mktemp -d "${TEMP_ROOT%/}/draid-flash-clear.XXXXXX"
TEMP_DIR="$(mktemp -d "${TEMP_ROOT%/}/draid-flash-clear.XXXXXX")" || exit 1
ZERO_FILE="$TEMP_DIR/flash-zero.bin"

# 生成与硬件 Flash 传输长度相同的全零输入文件。
if ! run_cmd dd if=/dev/zero of="$ZERO_FILE" bs="$FLASH_SIZE" count=1 status=none; then
    echo "错误：生成全零输入文件失败。" >&2
    exit 1
fi

for dev in "${DEVICES[@]}"; do
    safe_name="${dev//\//_}"
    readback_file="$TEMP_DIR/${safe_name}.readback.bin"

    echo "===== 清空 $dev Flash ====="
    if ! run_cmd nvme admin-passthru "$dev" \
        --opcode="$FLASH_WRITE_OPCODE" \
        --namespace-id="$NAMESPACE_ID" \
        --cdw10="$FLASH_CDW10" \
        --data-len="$FLASH_SIZE" \
        --input-file="$ZERO_FILE" \
        --write; then
        echo "失败：$dev Flash 写入命令失败。" >&2
        FAILED_DEVICES+=("$dev")
        continue
    fi

    # 回读完整 Flash，并保留原始二进制结果用于全零比较。
    printf '+ nvme admin-passthru %q --opcode=%q --namespace-id=%q --cdw10=%q --data-len=%q --read --raw-binary > %q\n' \
        "$dev" "$FLASH_READ_OPCODE" "$NAMESPACE_ID" "$FLASH_CDW10" "$FLASH_SIZE" "$readback_file"
    if ! nvme admin-passthru "$dev" \
        --opcode="$FLASH_READ_OPCODE" \
        --namespace-id="$NAMESPACE_ID" \
        --cdw10="$FLASH_CDW10" \
        --data-len="$FLASH_SIZE" \
        --read \
        --raw-binary > "$readback_file"; then
        echo "失败：$dev Flash 回读命令失败。" >&2
        FAILED_DEVICES+=("$dev")
        continue
    fi

    if ! run_cmd cmp --silent "$ZERO_FILE" "$readback_file"; then
        echo "失败：$dev Flash 回读内容不是完整 ${FLASH_SIZE}B 全零。" >&2
        FAILED_DEVICES+=("$dev")
        continue
    fi

    echo "===== Cache clear $dev ====="
    if ! run_cmd nvme admin-passthru "$dev" \
        --opcode="$CACHE_CLEAR_OPCODE" \
        --namespace-id="$NAMESPACE_ID"; then
        echo "失败：$dev Cache clear 命令失败。" >&2
        FAILED_DEVICES+=("$dev")
        continue
    fi

    echo "成功：$dev Flash 已清零并通过回读校验，Cache 已清空。"
done

if [ "${#FAILED_DEVICES[@]}" -gt 0 ]; then
    echo "清零或校验失败的设备：${FAILED_DEVICES[*]}" >&2
    exit 1
fi

echo "全部 CSD Flash 已清零并通过回读校验。"
