#!/bin/bash
set -euo pipefail

: "${NODE_IP:?NODE_IP is required}"
: "${TARGET_USER:?TARGET_USER is required}"
: "${REMOTE_DIR:?REMOTE_DIR is required}"
: "${BUILD_NUMBER:?BUILD_NUMBER is required}"
: "${QEMU_VM_TARGET:?QEMU_VM_TARGET is required}"

SSH_OPTS=${SSH_OPTS:-}
QEMU_VM_PASSWORD=${QEMU_VM_PASSWORD:-}
QEMU_VM_SSH_PORT=${QEMU_VM_SSH_PORT:-2233}
QEMU_VM_SCP_PORT=${QEMU_VM_SCP_PORT:-2233}
QEMU_KERNEL_BUILD_DIR=${QEMU_KERNEL_BUILD_DIR:-}

host_ssh() {
    ssh ${SSH_OPTS} "${TARGET_USER}@${NODE_IP}" "$@"
}

host_scp() {
    scp ${SSH_OPTS} "$@"
}

target_ssh() {
    if [ "${QEMU_VM_TARGET}" = "1" ]; then
        sshpass -p "${QEMU_VM_PASSWORD}" ssh ${SSH_OPTS} -p "${QEMU_VM_SSH_PORT}" "${TARGET_USER}@${NODE_IP}" "$@"
    else
        host_ssh "$@"
    fi
}

target_scp() {
    if [ "${QEMU_VM_TARGET}" = "1" ]; then
        sshpass -p "${QEMU_VM_PASSWORD}" scp ${SSH_OPTS} -P "${QEMU_VM_SCP_PORT}" "$@"
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
if ! insmod ./draid.ko; then
    echo "insmod ./draid.ko failed. Current related modules:" >&2
    grep -i draid /proc/modules >&2 || true
    exit 1
fi
grep -q "^${module_name} " /proc/modules
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
    command -v sshpass >/dev/null 2>&1 || {
        echo "sshpass is required on Jenkins server for QEMU VM login" >&2
        exit 1
    }

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
