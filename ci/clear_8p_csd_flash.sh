#!/usr/bin/env bash
set -euo pipefail

# After env cleanup / workspace deploy and before loading draid: find disks whose
# lsblk SIZE is 8P (dirty CSD flash presentation), map to NVMe controllers, and
# non-interactively clear CSD flash via flash-clear.sh.

NODE_IP=${NODE_IP:-unknown}
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
FLASH_CLEAR_SCRIPT=${FLASH_CLEAR_SCRIPT:-"${SCRIPT_DIR}/flash-clear.sh"}
LSBLK_BIN=${LSBLK_BIN:-lsblk}

is_8p_size() {
    case "$1" in
        8P|8.0P|8.00P) return 0 ;;
        *) return 1 ;;
    esac
}

namespace_to_controller() {
    local name="$1"
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

discover_8p_controllers() {
    CONTROLLERS=()
    local name size type ctrl
    while read -r name size type; do
        [ -n "${name:-}" ] || continue
        [ "${type:-}" = "disk" ] || continue
        is_8p_size "${size:-}" || continue
        if ! ctrl="$(namespace_to_controller "$name")"; then
            echo "[${NODE_IP}] skip non-nvme 8P disk: ${name} (${size})"
            continue
        fi
        if controller_seen "$ctrl"; then
            continue
        fi
        CONTROLLERS+=("$ctrl")
    done < <("${LSBLK_BIN}" -dn -o NAME,SIZE,TYPE 2>/dev/null || true)
}

echo "[${NODE_IP}] scan lsblk for 8P disks before loading draid"
discover_8p_controllers

if [ "${#CONTROLLERS[@]}" -eq 0 ]; then
    echo "[${NODE_IP}] no 8P disks found; skip CSD flash clear"
    exit 0
fi

echo "[${NODE_IP}] 8P disks mapped to controllers: ${CONTROLLERS[*]}"

if [ ! -x "${FLASH_CLEAR_SCRIPT}" ] && [ -f "${FLASH_CLEAR_SCRIPT}" ]; then
    chmod +x "${FLASH_CLEAR_SCRIPT}" || true
fi
if [ ! -f "${FLASH_CLEAR_SCRIPT}" ]; then
    echo "[${NODE_IP}] ERROR: flash-clear script not found: ${FLASH_CLEAR_SCRIPT}" >&2
    exit 1
fi

if ! command -v nvme >/dev/null 2>&1; then
    echo "[${NODE_IP}] ERROR: nvme command not found; install nvme-cli before CSD flash clear" >&2
    exit 1
fi

# flash-clear.sh prompts for CLEAR; feed it automatically for CI.
printf 'CLEAR\n' | "${FLASH_CLEAR_SCRIPT}" "${CONTROLLERS[@]}"
echo "[${NODE_IP}] CSD flash clear finished for: ${CONTROLLERS[*]}"
