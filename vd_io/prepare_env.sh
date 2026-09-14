#!/usr/bin/env bash
# DUT environment prepare for the env_prepare test case.
# Sequence (physical host):
#   reclaim host from QEMU (stop VM / unload draid / unbind vfio)
#   -> install dpraid
#   -> build draid (ACCEL_CDEV=y exposes /dev/draid_dbg_accel*)
#   -> CSD flash clear (SMOKE 5-step: rmmod -> insmod -> FORCE clear -> rmmod -> insmod)
#   -> restore VD/PD
set -euo pipefail

NODE_IP=${NODE_IP:-unknown}
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/.." && pwd)
REMOTE_DIR=${REMOTE_DIR:-${REPO_ROOT}}
DPRAID_STAGED=${DPRAID_STAGED:-"${REMOTE_DIR}/artifacts/dpraid"}
DRAID_DIR=${DRAID_DIR:-"${REMOTE_DIR}/kernel_driver/drivers/draid"}
export DRAID_DIR

echo "[${NODE_IP}] ===== prepare_env start ====="
echo "[${NODE_IP}] REMOTE_DIR=${REMOTE_DIR}"

# echo "[${NODE_IP}] enable DUT coredumps (ulimit/core_pattern/ptrace) + kdump before prepare"
# chmod +x "${SCRIPT_DIR}/enable_failure_coredumps.sh" "${SCRIPT_DIR}/enable_failure_kdump.sh" \
#     "${SCRIPT_DIR}/enable_draid_pending_debug.sh" 2>/dev/null || true
# NODE_IP="${NODE_IP}" REMOTE_DIR="${REMOTE_DIR}" "${SCRIPT_DIR}/enable_failure_coredumps.sh" || true
# NODE_IP="${NODE_IP}" REMOTE_DIR="${REMOTE_DIR}" "${SCRIPT_DIR}/enable_failure_kdump.sh" || true
# NODE_IP="${NODE_IP}" REMOTE_DIR="${REMOTE_DIR}" "${SCRIPT_DIR}/enable_draid_pending_debug.sh" || true

echo "[${NODE_IP}] (1/5) stop QEMU if running, unload draid, return devices to physical host"
chmod +x "${SCRIPT_DIR}/reclaim_physical_host.sh" 2>/dev/null || true
NODE_IP="${NODE_IP}" DRAID_DIR="${DRAID_DIR}" "${SCRIPT_DIR}/reclaim_physical_host.sh"

echo "[${NODE_IP}] (2/5) update dpraid"
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

echo "[${NODE_IP}] (3/5) rebuild draid.ko (ACCEL_CDEV=y)"
test -d "${DRAID_DIR}" || {
    echo "[${NODE_IP}] ERROR: draid source dir missing: ${DRAID_DIR}" >&2
    exit 1
}

# Same class of deps as SMOKE prepare_draid_driver.sh, plus ripgrep for portable-check.
install_draid_build_deps() {
    need_driver_deps=0
    for tool in make gcc insmod modinfo rg; do
        command -v "${tool}" >/dev/null 2>&1 || need_driver_deps=1
    done
    [ -e "/lib/modules/$(uname -r)/build" ] || need_driver_deps=1
    if [ "${need_driver_deps}" != "1" ]; then
        return 0
    fi
    echo "[${NODE_IP}] install draid build deps (make/gcc/headers/kmod/ripgrep)"
    if command -v apt-get >/dev/null 2>&1; then
        export DEBIAN_FRONTEND=noninteractive
        chmod +x "${SCRIPT_DIR}/ensure_ubuntu_china_mirrors.sh" 2>/dev/null || true
        NODE_IP="${NODE_IP}" bash "${SCRIPT_DIR}/ensure_ubuntu_china_mirrors.sh" || true
        apt_retry() {
            for attempt in 1 2 3; do
                "$@" && return 0
                echo "apt command failed, retry ${attempt}/3: $*" >&2
                sleep $((attempt * 10))
            done
            "$@"
        }
        apt_retry apt-get -o DPkg::Lock::Timeout=600 update
        apt_retry apt-get -o DPkg::Lock::Timeout=600 install -y \
            build-essential "linux-headers-$(uname -r)" kmod ripgrep
    elif command -v dnf >/dev/null 2>&1; then
        dnf install -y make gcc kernel-devel kmod ripgrep
    elif command -v yum >/dev/null 2>&1; then
        yum install -y make gcc kernel-devel kmod ripgrep
    else
        echo "[${NODE_IP}] ERROR: no supported package manager to install draid build deps" >&2
        exit 1
    fi
    for tool in make gcc insmod modinfo rg; do
        command -v "${tool}" >/dev/null 2>&1 || {
            echo "[${NODE_IP}] ERROR: missing tool after draid build dep install: ${tool}" >&2
            exit 1
        }
    done
    [ -e "/lib/modules/$(uname -r)/build" ] || {
        echo "[${NODE_IP}] ERROR: kernel build dir missing: /lib/modules/$(uname -r)/build" >&2
        exit 1
    }
}
install_draid_build_deps

(
    cd "${DRAID_DIR}"
    make -j 8 ACCEL_CDEV=y
    test -f ./draid.ko
)

draid_module_name() {
    local name
    name=$(modinfo -F name "${DRAID_DIR}/draid.ko" 2>/dev/null || true)
    printf '%s\n' "${name:-draid}"
}

unload_draid_module() {
    local module_name candidate
    module_name=$(draid_module_name)
    for candidate in "${module_name}" draid; do
        if [ -n "${candidate}" ] && grep -q "^${candidate} " /proc/modules; then
            rmmod "${candidate}" || modprobe -r "${candidate}" || true
        fi
    done
    for candidate in "${module_name}" draid; do
        if [ -n "${candidate}" ] && grep -q "^${candidate} " /proc/modules; then
            echo "[${NODE_IP}] kernel module ${candidate} still loaded after remove" >&2
            grep -i draid /proc/modules >&2 || true
            exit 1
        fi
    done
}

load_draid_module() {
    local module_name
    module_name=$(draid_module_name)
    test -f "${DRAID_DIR}/draid.ko"
    sync || true
    echo 3 >/proc/sys/vm/drop_caches 2>/dev/null || true
    (
        cd "${DRAID_DIR}"
        if ! insmod ./draid.ko; then
            sync || true
            echo 3 >/proc/sys/vm/drop_caches 2>/dev/null || true
            sleep 2
            insmod ./draid.ko
        fi
    )
    grep -q "^${module_name} " /proc/modules
    echo "[${NODE_IP}] draid module loaded: ${module_name}"
}

echo "[${NODE_IP}] (4/5) CSD flash clear (SMOKE 5-step: rmmod -> insmod -> FORCE clear -> rmmod -> insmod)"
chmod +x "${SCRIPT_DIR}/clear_8p_csd_flash.sh" "${SCRIPT_DIR}/flash-clear.sh" 2>/dev/null || true
# 1) rmmod
unload_draid_module
# 2) insmod (recreate /dev/draid_dbg_accel*)
load_draid_module
# 3) FORCE clear all accel devices
FORCE_CLEAR_ALL=1 NODE_IP="${NODE_IP}" "${SCRIPT_DIR}/clear_8p_csd_flash.sh"
# 4) rmmod
unload_draid_module
# 5) insmod (leave loaded for following cases)
load_draid_module

echo "[${NODE_IP}] (5/5) clear leftover VD/PD"
chmod +x "${SCRIPT_DIR}/restore_physical_raid_state.sh"
NODE_IP="${NODE_IP}" "${SCRIPT_DIR}/restore_physical_raid_state.sh"

# echo "[${NODE_IP}] enable unlimited cores + core_pattern + kdump + RAID1 pending debug for failure bundles"
# chmod +x "${SCRIPT_DIR}/enable_failure_coredumps.sh" "${SCRIPT_DIR}/enable_failure_kdump.sh" \
#     "${SCRIPT_DIR}/enable_draid_pending_debug.sh" 2>/dev/null || true
# NODE_IP="${NODE_IP}" REMOTE_DIR="${REMOTE_DIR}" "${SCRIPT_DIR}/enable_failure_coredumps.sh" || true
# NODE_IP="${NODE_IP}" REMOTE_DIR="${REMOTE_DIR}" "${SCRIPT_DIR}/enable_failure_kdump.sh" || true
# NODE_IP="${NODE_IP}" REMOTE_DIR="${REMOTE_DIR}" "${SCRIPT_DIR}/enable_draid_pending_debug.sh" || true

echo "[${NODE_IP}] ===== prepare_env done ====="
