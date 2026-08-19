#!/usr/bin/env bash
# Run on the DUT before each physical VD IO case (basic_io / basic_rebuild_io).
# Sequence: refresh dpraid -> rebuild+reload draid -> clear VD/PD.
# CSD flash clear is temporarily disabled.
set -euo pipefail

NODE_IP=${NODE_IP:-unknown}
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/.." && pwd)
REMOTE_DIR=${REMOTE_DIR:-${REPO_ROOT}}
DPRAID_STAGED=${DPRAID_STAGED:-"${REMOTE_DIR}/artifacts/dpraid"}
DRAID_DIR=${DRAID_DIR:-"${REMOTE_DIR}/kernel_driver/drivers/draid"}

echo "[${NODE_IP}] ===== prepare_physical_io_case start ====="
echo "[${NODE_IP}] REMOTE_DIR=${REMOTE_DIR}"

# echo "[${NODE_IP}] (1/4) clear dirty CSD flash"
# chmod +x "${SCRIPT_DIR}/clear_8p_csd_flash.sh" "${SCRIPT_DIR}/flash-clear.sh" 2>/dev/null || true
# NODE_IP="${NODE_IP}" "${SCRIPT_DIR}/clear_8p_csd_flash.sh"
echo "[${NODE_IP}] skip dirty CSD flash clear"

echo "[${NODE_IP}] (2/4) update dpraid"
if [ -x "${DPRAID_STAGED}" ]; then
    install -m 0755 "${DPRAID_STAGED}" /usr/bin/dpraid
    echo "[${NODE_IP}] installed dpraid from ${DPRAID_STAGED}"
elif [ -x /usr/bin/dpraid ]; then
    echo "[${NODE_IP}] staged dpraid not found; keep existing /usr/bin/dpraid"
else
    echo "[${NODE_IP}] ERROR: dpraid not available (${DPRAID_STAGED} or /usr/bin/dpraid)" >&2
    exit 1
fi
/usr/bin/dpraid --help >/dev/null


echo "[${NODE_IP}] (3/4) rebuild and reload draid (rmmod/insmod)"
test -d "${DRAID_DIR}" || {
    echo "[${NODE_IP}] ERROR: draid source dir missing: ${DRAID_DIR}" >&2
    exit 1
}
(
    cd "${DRAID_DIR}"
    make
    test -f ./draid.ko
    module_name=$(modinfo -F name ./draid.ko 2>/dev/null || true)
    module_name=${module_name:-draid}
    echo "[${NODE_IP}] draid.ko module name: ${module_name}"
    for candidate in "${module_name}" draid; do
        if [ -n "${candidate}" ] && grep -q "^${candidate} " /proc/modules; then
            rmmod "${candidate}" || modprobe -r "${candidate}"
        fi
    done
    for candidate in "${module_name}" draid; do
        if [ -n "${candidate}" ] && grep -q "^${candidate} " /proc/modules; then
            echo "[${NODE_IP}] kernel module ${candidate} still loaded after remove" >&2
            grep -i draid /proc/modules >&2 || true
            exit 1
        fi
    done
    sync || true
    echo 3 >/proc/sys/vm/drop_caches 2>/dev/null || true
    if ! insmod ./draid.ko; then
        sync || true
        echo 3 >/proc/sys/vm/drop_caches 2>/dev/null || true
        sleep 2
        insmod ./draid.ko
    fi
    grep -q "^${module_name} " /proc/modules
    echo "[${NODE_IP}] draid module loaded: ${module_name}"
)

echo "[${NODE_IP}] (4/4) clear leftover VD/PD"
chmod +x "${SCRIPT_DIR}/restore_physical_raid_state.sh"
NODE_IP="${NODE_IP}" "${SCRIPT_DIR}/restore_physical_raid_state.sh"

echo "[${NODE_IP}] ===== prepare_physical_io_case done ====="
