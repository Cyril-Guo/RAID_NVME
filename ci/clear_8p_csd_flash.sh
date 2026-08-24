#!/usr/bin/env bash
set -euo pipefail

# Find dirty CSD flash disks from lsblk (8P/9P SIZE) and/or nvme list
# (PB-scale total capacity such as 9.01 PB). Map namespaces to NVMe
# controllers, then non-interactively clear CSD flash via flash-clear.sh,
# which also runs Cache clear (admin-passthru opcode 0xD8).

NODE_IP=${NODE_IP:-unknown}
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
FLASH_CLEAR_SCRIPT=${FLASH_CLEAR_SCRIPT:-"${SCRIPT_DIR}/flash-clear.sh"}
LSBLK_BIN=${LSBLK_BIN:-lsblk}
NVME_BIN=${NVME_BIN:-nvme}

is_dirty_csd_size() {
    # Dirty CSD flash commonly appears as 8P/9P in lsblk (nvme list may show ~9 PB).
    # Real test drives are TB-scale and must not match.
    local size="${1:-}"
    size="${size// /}"
    case "$size" in
        8P|8.0P|8.00P|9P|9.0P|9.00P|9.01P) return 0 ;;
        8PiB|8.0PiB|9PiB|9.0PiB|9.01PiB) return 0 ;;
        8PB|8.0PB|8.00PB|9PB|9.0PB|9.00PB|9.01PB) return 0 ;;
    esac
    if [[ "$size" =~ ^[89](\.[0-9]+)?P(i?[Bb])?$ ]]; then
        return 0
    fi
    return 1
}

namespace_to_controller() {
    local name="$1"
    name="${name#/dev/}"
    if [[ "$name" =~ ^(nvme[0-9]+)n[0-9]+$ ]]; then
        printf '%s\n' "/dev/${BASH_REMATCH[1]}"
        return 0
    fi
    if [[ "$name" =~ ^nvme[0-9]+$ ]]; then
        printf '%s\n' "/dev/${name}"
        return 0
    fi
    return 1
}

controller_seen() {
    local needle="$1"
    local item
    for item in "${CONTROLLERS[@]:-}"; do
        if [ "$item" = "$needle" ]; then
            return 0
        fi
    done
    return 1
}

add_controller() {
    local name="$1"
    local size="$2"
    local source="$3"
    local ctrl
    if ! ctrl="$(namespace_to_controller "$name")"; then
        echo "[${NODE_IP}] skip non-nvme dirty-CSD disk from ${source}: ${name} (${size})"
        return 0
    fi
    if controller_seen "$ctrl"; then
        return 0
    fi
    echo "[${NODE_IP}] found dirty-CSD via ${source}: ${name} size=${size} -> ${ctrl}"
    CONTROLLERS+=("$ctrl")
}

discover_dirty_from_lsblk() {
    local name size type
    while read -r name size type; do
        [ -n "${name:-}" ] || continue
        [ "${type:-}" = "disk" ] || continue
        is_dirty_csd_size "${size:-}" || continue
        add_controller "$name" "$size" "lsblk"
    done < <("${LSBLK_BIN}" -dn -o NAME,SIZE,TYPE 2>/dev/null || true)
}

discover_dirty_from_nvme_list() {
    # Match total capacity after '/' in nvme list Usage column, e.g. "0.00 B / 9.01 PB".
    local line node size unit
    while IFS= read -r line; do
        [[ "$line" == /dev/nvme* ]] || continue
        if [[ "$line" =~ ^(/dev/nvme[0-9]+n[0-9]+)[[:space:]].*/[[:space:]]*([0-9]+(\.[0-9]+)?)[[:space:]]*([KMGTP]i?B) ]]; then
            node="${BASH_REMATCH[1]}"
            size="${BASH_REMATCH[2]}"
            unit="${BASH_REMATCH[4]}"
            is_dirty_csd_size "${size}${unit}" || continue
            add_controller "$node" "${size}${unit}" "nvme-list"
        fi
    done < <("${NVME_BIN}" list 2>/dev/null || true)
}

discover_dirty_csd_controllers() {
    CONTROLLERS=()
    echo "[${NODE_IP}] scan lsblk for dirty CSD flash disks (8P/9P)"
    "${LSBLK_BIN}" -dn -o NAME,SIZE,TYPE 2>/dev/null | sed "s/^/[${NODE_IP}] lsblk: /" || true
    discover_dirty_from_lsblk

    echo "[${NODE_IP}] scan nvme list for dirty CSD flash disks (PB-scale)"
    "${NVME_BIN}" list 2>/dev/null | sed "s/^/[${NODE_IP}] nvme-list: /" || true
    discover_dirty_from_nvme_list
}

discover_dirty_csd_controllers

if [ "${#CONTROLLERS[@]}" -eq 0 ]; then
    echo "[${NODE_IP}] no dirty-CSD disks found via lsblk or nvme list; skip CSD flash clear"
    exit 0
fi

echo "[${NODE_IP}] dirty-CSD disks mapped to controllers: ${CONTROLLERS[*]}"

if [ ! -x "${FLASH_CLEAR_SCRIPT}" ] && [ -f "${FLASH_CLEAR_SCRIPT}" ]; then
    chmod +x "${FLASH_CLEAR_SCRIPT}" || true
fi
if [ ! -f "${FLASH_CLEAR_SCRIPT}" ]; then
    echo "[${NODE_IP}] ERROR: flash-clear script not found: ${FLASH_CLEAR_SCRIPT}" >&2
    exit 1
fi

if ! command -v "${NVME_BIN}" >/dev/null 2>&1 && [ ! -x "${NVME_BIN}" ]; then
    echo "[${NODE_IP}] ERROR: nvme command not found; install nvme-cli before CSD flash clear" >&2
    exit 1
fi

# flash-clear.sh prompts for CLEAR; feed it automatically for CI.
printf 'CLEAR\n' | "${FLASH_CLEAR_SCRIPT}" "${CONTROLLERS[@]}"
echo "[${NODE_IP}] CSD flash clear finished for: ${CONTROLLERS[*]}"
