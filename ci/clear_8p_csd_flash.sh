#!/usr/bin/env bash
set -euo pipefail

# Find DAPU CSD PCI devices (Device 50d1) via lspci. When any device lacks
# "Kernel driver in use: draid-nvme", clear ALL /dev/draid_dbg_accel* nodes
# (ACCEL_CDEV=y, draid loaded). No nvmeN <-> accelN index mapping.

NODE_IP=${NODE_IP:-unknown}
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
FLASH_CLEAR_SCRIPT=${FLASH_CLEAR_SCRIPT:-"${SCRIPT_DIR}/flash-clear.sh"}
LSPCI_BIN=${LSPCI_BIN:-lspci}
NVME_BIN=${NVME_BIN:-nvme}
DRAID_ACCEL_DEV_PREFIX=${DRAID_ACCEL_DEV_PREFIX:-draid_dbg_accel}
DRAID_DEV_ROOT=${DRAID_DEV_ROOT:-/dev}
DAPU_CSD_LSPCI_MATCH=${DAPU_CSD_LSPCI_MATCH:-"Shenzhen DAPU Microelectronics Co., Ltd Device 50d1"}
DRAID_NVME_DRIVER=${DRAID_NVME_DRIVER:-draid-nvme}

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

any_dirty_dapu_csd() {
    local line bdf norm dirty=0

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
            echo "[${NODE_IP}] clean DAPU CSD ${norm}: Kernel driver in use: ${DRAID_NVME_DRIVER}"
            continue
        fi
        echo "[${NODE_IP}] dirty DAPU CSD ${norm}: missing Kernel driver in use: ${DRAID_NVME_DRIVER}"
        dirty=1
    done < <("${LSPCI_BIN}" -Dnn 2>/dev/null || "${LSPCI_BIN}" -nn 2>/dev/null || true)

    [ "${dirty}" = "1" ]
}

list_all_draid_accel_devices() {
    local path name
    DRAID_DEVICES=()

    if [ -n "${DRAID_ACCEL_DEVICES:-}" ]; then
        # Test/override: space-separated absolute paths.
        # shellcheck disable=SC2206
        DRAID_DEVICES=(${DRAID_ACCEL_DEVICES})
        return 0
    fi

    shopt -s nullglob
    for path in "${DRAID_DEV_ROOT}/${DRAID_ACCEL_DEV_PREFIX}"*; do
        name="$(basename "$path")"
        [[ "$name" =~ ^${DRAID_ACCEL_DEV_PREFIX}[0-9]+$ ]] || continue
        if [ "${DRAID_SKIP_DEVICE_CHECK:-0}" = "1" ] || [ -c "$path" ] || [ -e "$path" ]; then
            DRAID_DEVICES+=("$path")
        fi
    done
    shopt -u nullglob

    if [ "${#DRAID_DEVICES[@]}" -gt 0 ]; then
        # Stable order: accel0, accel1, ...
        mapfile -t DRAID_DEVICES < <(printf '%s\n' "${DRAID_DEVICES[@]}" | sort -V)
    fi
}

if ! any_dirty_dapu_csd; then
    echo "[${NODE_IP}] no dirty DAPU CSD devices (all bound to ${DRAID_NVME_DRIVER}); skip CSD flash clear"
    exit 0
fi

list_all_draid_accel_devices

if [ "${#DRAID_DEVICES[@]}" -eq 0 ]; then
    echo "[${NODE_IP}] ERROR: dirty DAPU CSD found but no /dev/${DRAID_ACCEL_DEV_PREFIX}* devices (load draid.ko with ACCEL_CDEV=y first)" >&2
    exit 1
fi

echo "[${NODE_IP}] clear ALL draid accel devices: ${DRAID_DEVICES[*]}"

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
