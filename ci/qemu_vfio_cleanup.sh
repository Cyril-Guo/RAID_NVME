#!/bin/bash
set -euo pipefail

: "${NODE_IP:?NODE_IP is required}"
: "${TARGET_USER:?TARGET_USER is required}"
: "${QEMU_VM_WORKDIR:?QEMU_VM_WORKDIR is required}"
: "${QEMU_VFIO_BIND_SCRIPT:?QEMU_VFIO_BIND_SCRIPT is required}"
: "${BUILD_NUMBER:?BUILD_NUMBER is required}"

SSH_OPTS=${SSH_OPTS:-}
QEMU_VM_PASSWORD=${QEMU_VM_PASSWORD:-}
QEMU_VM_SSH_PORT=${QEMU_VM_SSH_PORT:-2233}
CLEANUP_REASON=${CLEANUP_REASON:-return NVMe devices to physical host}
POWER_OFF_QEMU=${POWER_OFF_QEMU:-0}

host_ssh() {
    ssh ${SSH_OPTS} "${TARGET_USER}@${NODE_IP}" "$@"
}

qemu_ssh() {
    sshpass -p "${QEMU_VM_PASSWORD}" ssh ${SSH_OPTS} -p "${QEMU_VM_SSH_PORT}" "${TARGET_USER}@${NODE_IP}" "$@"
}

echo "[${NODE_IP}] ${CLEANUP_REASON}"

if [ "${POWER_OFF_QEMU}" = "1" ]; then
    qemu_ssh 'sync; nohup sh -c "sleep 1; poweroff" >/dev/null 2>&1 &' >/dev/null 2>&1 || true
    for attempt in $(seq 1 30); do
        if qemu_ssh 'true' >/dev/null 2>&1; then
            echo "[${NODE_IP}] waiting for QEMU VM shutdown, attempt ${attempt}/30"
            sleep 2
        else
            echo "[${NODE_IP}] QEMU VM SSH is down"
            break
        fi
    done
fi

host_ssh "NODE_IP='${NODE_IP}' BUILD_NUMBER='${BUILD_NUMBER}' QEMU_VM_WORKDIR='${QEMU_VM_WORKDIR}' QEMU_VFIO_BIND_SCRIPT='${QEMU_VFIO_BIND_SCRIPT}' POWER_OFF_QEMU='${POWER_OFF_QEMU}' bash -s" <<'HOST_CLEANUP'
set -euo pipefail
cd "${QEMU_VM_WORKDIR}" || exit 0
test -x "${QEMU_VFIO_BIND_SCRIPT}" || {
    echo "QEMU vfio bind script not found or not executable: ${QEMU_VM_WORKDIR}/${QEMU_VFIO_BIND_SCRIPT}" >&2
    exit 1
}

if [ "${POWER_OFF_QEMU}" = "1" ]; then
    qemu_pids=$(pgrep -f "qemu-system-x86_64.*vm-serial.log" || true)
    if [ -n "${qemu_pids}" ]; then
        echo "[${NODE_IP}] force stop stale QEMU processes on host: ${qemu_pids}"
        kill ${qemu_pids} >/dev/null 2>&1 || true
        for attempt in $(seq 1 15); do
            still_running=""
            for qemu_pid in ${qemu_pids}; do
                kill -0 "${qemu_pid}" >/dev/null 2>&1 && still_running="${still_running} ${qemu_pid}" || true
            done
            [ -z "${still_running}" ] && break
            echo "[${NODE_IP}] waiting for stale QEMU process exit, attempt ${attempt}/15:${still_running}"
            sleep 2
        done
        for qemu_pid in ${qemu_pids}; do
            kill -0 "${qemu_pid}" >/dev/null 2>&1 && kill -9 "${qemu_pid}" >/dev/null 2>&1 || true
        done
    fi
fi

device_file=".jenkins_nvme_${BUILD_NUMBER}_vfio_devices"
if [ ! -s "$device_file" ]; then
    echo "[${NODE_IP}] no recorded QEMU vfio devices to unbind"
    for pci_path in /sys/bus/pci/devices/*; do
        [ -e "$pci_path/class" ] || continue
        pci_class=$(cat "$pci_path/class")
        [ "$pci_class" = "0x010802" ] || continue
        driver_path=$(readlink -f "$pci_path/driver" 2>/dev/null || true)
        driver=${driver_path##*/}
        [ "$driver" = "vfio-pci" ] || continue
        dev=$(basename "$pci_path")
        echo "[${NODE_IP}] fallback unbind vfio NVMe PCI device back to host: ${dev}"
        DEV="$dev" "${QEMU_VFIO_BIND_SCRIPT}" unbind || true
    done
else
    while read -r dev; do
        [ -n "$dev" ] || continue
        echo "[${NODE_IP}] unbind NVMe PCI device back to host: ${dev}"
        DEV="$dev" "${QEMU_VFIO_BIND_SCRIPT}" unbind || true
    done < "$device_file"
fi

echo 1 > /sys/bus/pci/rescan || true
sleep 5
nvme list || true
HOST_CLEANUP
