#!/usr/bin/env bash
set -euo pipefail

# Find DAPU CSD PCI devices (Device 50d1) via lspci. When "Kernel driver in use:
# draid-nvme" is missing the CSD is dirty and needs flash/cache clear on the mapped
# /dev/draid_dbg_accel* node (ACCEL_CDEV=y, draid loaded).

NODE_IP=${NODE_IP:-unknown}
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
FLASH_CLEAR_SCRIPT=${FLASH_CLEAR_SCRIPT:-"${SCRIPT_DIR}/flash-clear.sh"}
LSPCI_BIN=${LSPCI_BIN:-lspci}
NVME_BIN=${NVME_BIN:-nvme}
DRAID_ACCEL_DEV_PREFIX=${DRAID_ACCEL_DEV_PREFIX:-draid_dbg_accel}
DAPU_CSD_LSPCI_MATCH=${DAPU_CSD_LSPCI_MATCH:-"Shenzhen DAPU Microelectronics Co., Ltd Device 50d1"}
DRAID_NVME_DRIVER=${DRAID_NVME_DRIVER:-draid-nvme}
SYSFS_ROOT=${SYSFS_ROOT:-/sys}

normalize_bdf() {
    local bdf="${1,,}"
    if [[ "$bdf" =~ ^[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-9a-f]$ ]]; then
        printf '%s\n' "$bdf"
        return 0
    fi
    if [[ "$bdf" =~ ^[0-9a-f]{2}:[0-9a-f]{2}\.[0-9a-f]$ ]]; then
        printf '0000:%s\n' "$bdf"
        return 0
    fi
    return 1
}

bdf_matches() {
    local path="$1"
    local bdf="$2"
    local base
    base="$(basename "$path")"
    [ "$base" = "$bdf" ] || [[ "$path" == *"/${bdf}" ]]
}

bdf_to_draid_accel_dev() {
    local bdf="$1"
    local accel resolved nvme_ctrl idx pair map_bdf map_dev

    if [ -n "${DRAID_ACCEL_DEV_MAP:-}" ]; then
        IFS=',' read -r -a _pairs <<< "${DRAID_ACCEL_DEV_MAP}"
        for pair in "${_pairs[@]}"; do
            map_bdf="${pair%%=*}"
            map_dev="${pair#*=}"
            map_bdf="$(normalize_bdf "$map_bdf" 2>/dev/null || printf '%s' "$map_bdf")"
            if [ "$map_bdf" = "$bdf" ]; then
                printf '%s\n' "$map_dev"
                return 0
            fi
        done
    fi

    for accel in "${SYSFS_ROOT}/class/draid_dbg_accel/${DRAID_ACCEL_DEV_PREFIX}"*; do
        [ -e "${accel}/device" ] || continue
        resolved="$(readlink -f "${accel}/device" 2>/dev/null || true)"
        [ -n "$resolved" ] || continue
        if bdf_matches "$resolved" "$bdf"; then
            printf '/dev/%s\n' "$(basename "$accel")"
            return 0
        fi
    done

    for nvme_ctrl in "${SYSFS_ROOT}/bus/pci/devices/${bdf}/nvme/nvme"*; do
        [ -e "$nvme_ctrl" ] || continue
        if [[ "$(basename "$nvme_ctrl")" =~ ^nvme([0-9]+)$ ]]; then
            idx="${BASH_REMATCH[1]}"
            printf '/dev/%s%s\n' "${DRAID_ACCEL_DEV_PREFIX}" "${idx}"
            return 0
        fi
    done

    return 1
}

device_seen() {
    local needle="$1"
    local item
    for item in "${DRAID_DEVICES[@]:-}"; do
        if [ "$item" = "$needle" ]; then
            return 0
        fi
    done
    return 1
}

add_draid_device_path() {
    local dev="$1"
    local bdf="$2"
    if device_seen "$dev"; then
        return 0
    fi
    echo "[${NODE_IP}] dirty DAPU CSD ${bdf} -> ${dev} (missing Kernel driver in use: ${DRAID_NVME_DRIVER})"
    DRAID_DEVICES+=("$dev")
}

has_draid_nvme_driver_bound() {
    local bdf="$1"
    local detail short_bdf
    short_bdf="${bdf#0000:}"
    detail="$("${LSPCI_BIN}" -s "$bdf" -k 2>/dev/null || true)"
    if [ -z "$detail" ] && [ "$short_bdf" != "$bdf" ]; then
        detail="$("${LSPCI_BIN}" -s "$short_bdf" -k 2>/dev/null || true)"
    fi
    detail="${detail//$'\r'/}"
    grep -Fq "Kernel driver in use: ${DRAID_NVME_DRIVER}" <<< "$detail"
}

discover_dirty_dapu_csd_devices() {
    DRAID_DEVICES=()
    local line bdf norm dev

    echo "[${NODE_IP}] scan lspci for DAPU CSD devices (${DAPU_CSD_LSPCI_MATCH})"
    while IFS= read -r line; do
        [ -n "${line:-}" ] || continue
        [[ "$line" == *"${DAPU_CSD_LSPCI_MATCH}"* ]] || continue
        bdf="$(awk '{print $1}' <<< "$line")"
        [ -n "$bdf" ] || continue
        norm="$(normalize_bdf "$bdf")" || {
            echo "[${NODE_IP}] skip unparseable PCI BDF from lspci: ${bdf}" >&2
            continue
        }
        echo "[${NODE_IP}] lspci: ${line}"
        if has_draid_nvme_driver_bound "$norm"; then
            echo "[${NODE_IP}] skip clean DAPU CSD ${norm}: Kernel driver in use: ${DRAID_NVME_DRIVER}"
            continue
        fi
        if ! dev="$(bdf_to_draid_accel_dev "$norm")"; then
            echo "[${NODE_IP}] ERROR: cannot map dirty DAPU CSD ${norm} to /dev/${DRAID_ACCEL_DEV_PREFIX}*" >&2
            exit 1
        fi
        add_draid_device_path "$dev" "$norm"
    done < <("${LSPCI_BIN}" -Dnn 2>/dev/null || "${LSPCI_BIN}" -nn 2>/dev/null || true)
}

discover_dirty_dapu_csd_devices

if [ "${#DRAID_DEVICES[@]}" -eq 0 ]; then
    echo "[${NODE_IP}] no dirty DAPU CSD devices (all bound to ${DRAID_NVME_DRIVER}); skip CSD flash clear"
    exit 0
fi

echo "[${NODE_IP}] dirty DAPU CSD devices mapped to draid accel: ${DRAID_DEVICES[*]}"

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

if [ "${DRAID_SKIP_DEVICE_CHECK:-0}" != "1" ]; then
    for dev in "${DRAID_DEVICES[@]}"; do
        if [ ! -c "$dev" ]; then
            echo "[${NODE_IP}] ERROR: draid accel device missing: ${dev} (load draid.ko with ACCEL_CDEV=y first)" >&2
            exit 1
        fi
    done
fi

# flash-clear.sh prompts for CLEAR; feed it automatically for CI.
printf 'CLEAR\n' | "${FLASH_CLEAR_SCRIPT}" "${DRAID_DEVICES[@]}"
echo "[${NODE_IP}] CSD flash clear finished for: ${DRAID_DEVICES[*]}"
