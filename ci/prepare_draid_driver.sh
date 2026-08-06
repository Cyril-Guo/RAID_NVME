#!/bin/bash
set -euo pipefail

: "${NODE_IP:?NODE_IP is required}"
: "${TARGET_USER:?TARGET_USER is required}"
: "${REMOTE_DIR:?REMOTE_DIR is required}"
: "${BUILD_NUMBER:?BUILD_NUMBER is required}"
: "${QEMU_VM_TARGET:?QEMU_VM_TARGET is required}"

SSH_OPTS=${SSH_OPTS:-}
TARGET_PASSWORD=${TARGET_PASSWORD:-123456}
QEMU_VM_PASSWORD=${QEMU_VM_PASSWORD:-}
QEMU_VM_SSH_PORT=${QEMU_VM_SSH_PORT:-2233}
QEMU_VM_SCP_PORT=${QEMU_VM_SCP_PORT:-2233}
QEMU_KERNEL_BUILD_DIR=${QEMU_KERNEL_BUILD_DIR:-}

host_ssh() {
    SSHPASS="${TARGET_PASSWORD}" sshpass -e ssh ${SSH_OPTS} "${TARGET_USER}@${NODE_IP}" "$@"
}

host_scp() {
    SSHPASS="${TARGET_PASSWORD}" sshpass -e scp ${SSH_OPTS} "$@"
}

target_ssh() {
    if [ "${QEMU_VM_TARGET}" = "1" ]; then
        SSHPASS="${QEMU_VM_PASSWORD}" sshpass -e ssh ${SSH_OPTS} -p "${QEMU_VM_SSH_PORT}" "${TARGET_USER}@${NODE_IP}" "$@"
    else
        host_ssh "$@"
    fi
}

target_scp() {
    if [ "${QEMU_VM_TARGET}" = "1" ]; then
        SSHPASS="${QEMU_VM_PASSWORD}" sshpass -e scp ${SSH_OPTS} -P "${QEMU_VM_SCP_PORT}" "$@"
    else
        host_scp "$@"
    fi
}

reload_remote_module() {
    target_ssh "REMOTE_DIR='${REMOTE_DIR}' bash -s" <<'REMOTE_RELOAD'
set -euo pipefail
cd "${REMOTE_DIR}/kernel_driver/drivers/draid"
test -f ./draid.ko
module_name=$(modinfo -F name ./draid.ko 2>/dev/null || true)
module_name=${module_name:-draid}
echo "draid.ko module name: ${module_name}"
for candidate in "${module_name}" draid; do
    if [ -n "${candidate}" ] && grep -q "^${candidate} " /proc/modules; then
        rmmod "${candidate}" || modprobe -r "${candidate}"
    fi
done
for candidate in "${module_name}" draid; do
    if [ -n "${candidate}" ] && grep -q "^${candidate} " /proc/modules; then
        echo "kernel module ${candidate} is still loaded after remove attempt" >&2
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
fi
if ! grep -q "^${module_name} " /proc/modules && ! insmod ./draid.ko; then
    echo "insmod ./draid.ko failed. Current related modules:" >&2
    grep -i draid /proc/modules >&2 || true
    echo "memory status after insmod failure:" >&2
    free -h >&2 || true
    grep -E '^(MemTotal|MemFree|MemAvailable|Buffers|Cached|SwapTotal|SwapFree|VmallocTotal|VmallocUsed|VmallocChunk):' /proc/meminfo >&2 || true
    echo "dmesg tail after insmod failure:" >&2
    dmesg | tail -n 160 >&2 || true
    exit 1
fi
grep -q "^${module_name} " /proc/modules

DRAID_READY_MAX_ATTEMPTS=${DRAID_READY_MAX_ATTEMPTS:-120}
DRAID_READY_RETRY_SECONDS=${DRAID_READY_RETRY_SECONDS:-2}

parse_controller_states() {
    awk '
        $1 ~ /^[0-9]+$/ {
            state = "unknown"
            for (i = 2; i <= NF; i++) {
                value = tolower($i)
                if (value == "online") {
                    state = "online"
                    break
                }
                if (value == "offline" || value == "offl") {
                    state = "offline"
                    break
                }
            }
            print $1, state
        }
    '
}

wait_for_draid_initialization() {
    attempt=1
    while [ "${attempt}" -le "${DRAID_READY_MAX_ATTEMPTS}" ]; do
        if DRAID_SHOW_OUTPUT=$(dpraid show 2>&1); then
            DRAID_CONTROLLER_STATES=$(printf '%s\n' "${DRAID_SHOW_OUTPUT}" | parse_controller_states)
            controller_count=$(printf '%s\n' "${DRAID_CONTROLLER_STATES}" | awk 'NF == 2 { count++ } END { print count + 0 }')
            unknown_count=$(printf '%s\n' "${DRAID_CONTROLLER_STATES}" | awk '$2 == "unknown" { count++ } END { print count + 0 }')
            if [ "${controller_count}" -gt 0 ] && [ "${unknown_count}" -eq 0 ]; then
                printf '%s\n' "${DRAID_SHOW_OUTPUT}"
                return 0
            fi
        fi
        echo "Waiting for draid controller initialization (${attempt}/${DRAID_READY_MAX_ATTEMPTS})..."
        sleep "${DRAID_READY_RETRY_SECONDS}"
        attempt=$((attempt + 1))
    done

    echo "draid controllers did not finish initialization in time. Last dpraid show output:" >&2
    printf '%s\n' "${DRAID_SHOW_OUTPUT:-<no output>}" >&2
    return 1
}

wait_for_all_draid_controllers_online() {
    expected_ids="$1"
    expected_count=$(printf '%s\n' "${expected_ids}" | awk 'NF == 1 { count++ } END { print count + 0 }')
    attempt=1

    while [ "${attempt}" -le "${DRAID_READY_MAX_ATTEMPTS}" ]; do
        if DRAID_SHOW_OUTPUT=$(dpraid show 2>&1); then
            DRAID_CONTROLLER_STATES=$(printf '%s\n' "${DRAID_SHOW_OUTPUT}" | parse_controller_states)
            current_count=$(printf '%s\n' "${DRAID_CONTROLLER_STATES}" | awk 'NF == 2 { count++ } END { print count + 0 }')
            non_online_count=$(printf '%s\n' "${DRAID_CONTROLLER_STATES}" | awk '$2 != "online" { count++ } END { print count + 0 }')
            missing_count=0
            for controller_id in ${expected_ids}; do
                if ! printf '%s\n' "${DRAID_CONTROLLER_STATES}" | awk -v id="${controller_id}" '$1 == id && $2 == "online" { found = 1 } END { exit !found }'; then
                    missing_count=$((missing_count + 1))
                fi
            done

            if [ "${expected_count}" -gt 0 ] &&
               [ "${current_count}" -eq "${expected_count}" ] &&
               [ "${non_online_count}" -eq 0 ] &&
               [ "${missing_count}" -eq 0 ]; then
                echo "All draid controllers are Online:"
                printf '%s\n' "${DRAID_SHOW_OUTPUT}"
                return 0
            fi
        fi
        echo "Waiting for all draid controllers to become Online (${attempt}/${DRAID_READY_MAX_ATTEMPTS})..."
        sleep "${DRAID_READY_RETRY_SECONDS}"
        attempt=$((attempt + 1))
    done

    echo "Not all draid controllers became Online in time. Last dpraid show output:" >&2
    printf '%s\n' "${DRAID_SHOW_OUTPUT:-<no output>}" >&2
    return 1
}

# Controller state check/reset is intentionally disabled. Loading draid no longer
# runs `dpraid show`, `reset-and-online`, or waits for all controllers to become Online.
# command -v dpraid >/dev/null 2>&1 || {
#     echo "dpraid is required to verify draid controller state" >&2
#     exit 1
# }
#
# wait_for_draid_initialization
# expected_controller_ids=$(printf '%s\n' "${DRAID_CONTROLLER_STATES}" | awk '{ print $1 }')
# offline_controller_ids=$(printf '%s\n' "${DRAID_CONTROLLER_STATES}" | awk '$2 == "offline" { print $1 }')
#
# for controller_id in ${offline_controller_ids}; do
#     echo "Controller ${controller_id} is Offline; run reset-and-online."
#     dpraid "/c${controller_id}" reset-and-online --force
# done
#
# wait_for_all_draid_controllers_online "${expected_controller_ids}"
REMOTE_RELOAD
}

install_driver_build_deps() {
    target_ssh 'bash -s' <<'REMOTE_DEPS'
set -euo pipefail
need_driver_deps=0
for tool in make gcc insmod modinfo; do
    command -v "${tool}" >/dev/null 2>&1 || need_driver_deps=1
done
[ -e "/lib/modules/$(uname -r)/build" ] || need_driver_deps=1
if [ "${need_driver_deps}" = "1" ]; then
    if command -v apt-get >/dev/null 2>&1; then
        export DEBIAN_FRONTEND=noninteractive
        apt_retry() {
            for attempt in 1 2 3; do
                "$@" && return 0
                echo "apt command failed, retry ${attempt}/3: $*" >&2
                sleep $((attempt * 10))
            done
            "$@"
        }
        apt_retry apt-get -o DPkg::Lock::Timeout=600 update
        apt_retry apt-get -o DPkg::Lock::Timeout=600 install -y build-essential "linux-headers-$(uname -r)" kmod
    elif command -v dnf >/dev/null 2>&1; then
        dnf install -y make gcc kernel-devel kmod
    elif command -v yum >/dev/null 2>&1; then
        yum install -y make gcc kernel-devel kmod
    fi
fi
REMOTE_DEPS
}

if [ "${QEMU_VM_TARGET}" = "1" ]; then
    : "${QEMU_VM_PASSWORD:?QEMU_VM_PASSWORD is required for QEMU target}"
    : "${QEMU_KERNEL_BUILD_DIR:?QEMU_KERNEL_BUILD_DIR is required for QEMU target}"
    SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
    chmod +x "${SCRIPT_DIR}/ensure_sshpass.sh"
    "${SCRIPT_DIR}/ensure_sshpass.sh"

    host_build_dir="/tmp/draid_build_${BUILD_NUMBER}"
    host_module="/tmp/draid_${BUILD_NUMBER}.ko"
    host_archive="/tmp/draid_src_${BUILD_NUMBER}.tar.gz"
    local_archive="draid_src_${NODE_IP}_${BUILD_NUMBER}.tar.gz"
    local_module="draid_${NODE_IP}_${BUILD_NUMBER}.ko"
    local_draid_src="kernel_driver/drivers/draid"
    trap 'rm -f "${local_archive:-}" "${local_module:-}"' EXIT

    test -d "${local_draid_src}" || {
        echo "Local kernel_driver draid source not found: ${local_draid_src}" >&2
        echo "kernel_driver checkout is required before preparing QEMU draid driver" >&2
        exit 1
    }
    test -f "${local_draid_src}/Makefile" || {
        echo "Local kernel_driver draid source has no Makefile: ${local_draid_src}" >&2
        exit 1
    }

    host_ssh "QEMU_KERNEL_BUILD_DIR='${QEMU_KERNEL_BUILD_DIR}' host_build_dir='${host_build_dir}' bash -s" <<'HOST_INIT'
set -euo pipefail
test -d "${QEMU_KERNEL_BUILD_DIR}" || {
    echo "QEMU kernel build dir not found: ${QEMU_KERNEL_BUILD_DIR}" >&2
    exit 1
}
test -f "${QEMU_KERNEL_BUILD_DIR}/Makefile" || {
    echo "QEMU kernel build dir has no Makefile: ${QEMU_KERNEL_BUILD_DIR}" >&2
    exit 1
}
rm -rf "${host_build_dir}"
mkdir -p "${host_build_dir}"
HOST_INIT

    rm -f "${local_archive}"
    tar -czf "${local_archive}" -C "${local_draid_src}" .
    host_scp "${local_archive}" "${TARGET_USER}@${NODE_IP}:${host_archive}"
    rm -f "${local_archive}"
    host_ssh "host_archive='${host_archive}' host_build_dir='${host_build_dir}' bash -s" <<'HOST_EXTRACT'
set -euo pipefail
test -f "${host_archive}" || {
    echo "Uploaded draid source archive not found: ${host_archive}" >&2
    exit 1
}
tar -xzf "${host_archive}" -C "${host_build_dir}"
rm -f "${host_archive}"
HOST_EXTRACT
    host_ssh "QEMU_KERNEL_BUILD_DIR='${QEMU_KERNEL_BUILD_DIR}' host_build_dir='${host_build_dir}' host_module='${host_module}' bash -s" <<'HOST_BUILD'
set -euo pipefail
command -v make >/dev/null 2>&1 || { echo "make is required on QEMU host for draid build" >&2; exit 1; }
command -v gcc >/dev/null 2>&1 || { echo "gcc is required on QEMU host for draid build" >&2; exit 1; }
make -C "${QEMU_KERNEL_BUILD_DIR}" M="${host_build_dir}" modules
test -f "${host_build_dir}/draid.ko"
cp -f "${host_build_dir}/draid.ko" "${host_module}"
HOST_BUILD

    host_scp "${TARGET_USER}@${NODE_IP}:${host_module}" "${local_module}"
    target_ssh "mkdir -p '${REMOTE_DIR}/kernel_driver/drivers/draid'"
    target_scp "${local_module}" "${TARGET_USER}@${NODE_IP}:${REMOTE_DIR}/kernel_driver/drivers/draid/draid.ko"
    rm -f "${local_module}"
    host_ssh "rm -rf '${host_build_dir}' '${host_module}' '${host_archive}'" || true
    reload_remote_module
else
    install_driver_build_deps
    target_ssh "REMOTE_DIR='${REMOTE_DIR}' bash -s" <<'REMOTE_BUILD'
set -euo pipefail
cd "${REMOTE_DIR}/kernel_driver/drivers/draid"
make
test -f ./draid.ko
REMOTE_BUILD
    reload_remote_module
fi
