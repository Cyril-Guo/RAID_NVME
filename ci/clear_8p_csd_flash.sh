#!/usr/bin/env bash
set -euo pipefail

# Find disks whose lsblk SIZE looks like dirty CSD flash (PB-scale, typically
# shown as 8P/9P), map namespaces to NVMe controllers, non-interactively clear
# CSD flash via flash-clear.sh, then run Cache clear (admin-passthru opcode 0xD8).

NODE_IP=${NODE_IP:-unknown}
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
FLASH_CLEAR_SCRIPT=${FLASH_CLEAR_SCRIPT:-"${SCRIPT_DIR}/flash-clear.sh"}
LSBLK_BIN=${LSBLK_BIN:-lsblk}

is_dirty_csd_size() {
    # Dirty CSD flash commonly appears as 8P/9P in lsblk (nvme list may show ~9 PB).
    # Real test drives are TB-scale and must not match.
    case "$1" in
        8P|8.0P|8.00P|9P|9.0P|9.00P|9.01P) return 0 ;;
    esac
    if [[ "$1" =~ ^[89](\.[0-9]+)?P$ ]]; then
        return 0
    fi
    return 1
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

discover_dirty_csd_controllers() {
    CONTROLLERS=()
    local name size type ctrl
    while read -r name size type; do
        [ -n "${name:-}" ] || continue
        [ "${type:-}" = "disk" ] || continue
        is_dirty_csd_size "${size:-}" || continue
        if ! ctrl="$(namespace_to_controller "$name")"; then
            echo "[${NODE_IP}] skip non-nvme dirty-CSD disk: ${name} (${size})"
            continue
        fi
        if controller_seen "$ctrl"; then
            continue
        fi
        echo "[${NODE_IP}] found dirty-CSD size disk: ${name} size=${size} -> ${ctrl}"
        CONTROLLERS+=("$ctrl")
    done < <("${LSBLK_BIN}" -dn -o NAME,SIZE,TYPE 2>/dev/null || true)
}

echo "[${NODE_IP}] scan lsblk for dirty CSD flash disks (8P/9P)"
"${LSBLK_BIN}" -dn -o NAME,SIZE,TYPE 2>/dev/null | sed "s/^/[${NODE_IP}] lsblk: /" || true
discover_dirty_csd_controllers

if [ "${#CONTROLLERS[@]}" -eq 0 ]; then
    echo "[${NODE_IP}] no dirty-CSD (8P/9P) disks found; skip CSD flash clear"
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

if ! command -v nvme >/dev/null 2>&1; then
    echo "[${NODE_IP}] ERROR: nvme command not found; install nvme-cli before CSD flash clear" >&2
    exit 1
fi

# flash-clear.sh prompts for CLEAR; feed it automatically for CI.
printf 'CLEAR\n' | "${FLASH_CLEAR_SCRIPT}" "${CONTROLLERS[@]}"
echo "[${NODE_IP}] CSD flash clear finished for: ${CONTROLLERS[*]}"
