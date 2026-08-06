#!/bin/bash
set -euo pipefail

: "${NODE_IP:?NODE_IP is required}"
: "${TARGET_USER:?TARGET_USER is required}"
: "${QEMU_VM_WORKDIR:?QEMU_VM_WORKDIR is required}"
: "${QEMU_VFIO_BIND_SCRIPT:?QEMU_VFIO_BIND_SCRIPT is required}"
: "${BUILD_NUMBER:?BUILD_NUMBER is required}"

SSH_OPTS=${SSH_OPTS:-}
TARGET_PASSWORD=${TARGET_PASSWORD:-123456}
QEMU_VM_PASSWORD=${QEMU_VM_PASSWORD:-}
QEMU_VM_SSH_PORT=${QEMU_VM_SSH_PORT:-2233}
CLEANUP_REASON=${CLEANUP_REASON:-return NVMe devices to physical host}
POWER_OFF_QEMU=${POWER_OFF_QEMU:-0}

host_ssh() {
    SSHPASS="${TARGET_PASSWORD}" sshpass -e ssh ${SSH_OPTS} "${TARGET_USER}@${NODE_IP}" "$@"
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

VFIO_BIND_TIMEOUT_SECONDS=${VFIO_BIND_TIMEOUT_SECONDS:-30}
unbind_failed=0

run_vfio_bind_action() {
    local action="$1"
    local dev="$2"
    local rc=0

    if command -v timeout >/dev/null 2>&1; then
        set +e
        timeout --kill-after=5s "${VFIO_BIND_TIMEOUT_SECONDS}s" env DEV="$dev" "${QEMU_VFIO_BIND_SCRIPT}" "$action"
        rc=$?
        set -e
    else
        set +e
        DEV="$dev" "${QEMU_VFIO_BIND_SCRIPT}" "$action"
        rc=$?
        set -e
    fi

    if [ "$rc" -ne 0 ]; then
        if [ "$rc" -eq 124 ] || [ "$rc" -eq 137 ]; then
            echo "[${NODE_IP}] vfio ${action} timed out after ${VFIO_BIND_TIMEOUT_SECONDS}s: ${dev}" >&2
        else
            echo "[${NODE_IP}] vfio ${action} failed rc=${rc}: ${dev}" >&2
        fi
        return "$rc"
    fi
}

list_vfio_nvme_devices() {
    for pci_path in /sys/bus/pci/devices/*; do
        [ -e "$pci_path/class" ] || continue
        pci_class=$(cat "$pci_path/class")
        [ "$pci_class" = "0x010802" ] || continue
        driver_path=$(readlink -f "$pci_path/driver" 2>/dev/null || true)
        driver=${driver_path##*/}
        [ "$driver" = "vfio-pci" ] || continue
        basename "$pci_path"
    done
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

if [ ! -d "${QEMU_VM_WORKDIR}" ]; then
    echo "[${NODE_IP}] QEMU workdir not found: ${QEMU_VM_WORKDIR}" >&2
    remaining=$(list_vfio_nvme_devices | tr '\n' ' ')
    if [ -n "$(printf '%s' "${remaining}" | tr -d ' ')" ]; then
        echo "[${NODE_IP}] ERROR: vfio NVMe devices still bound without workdir/bind script:${remaining}" >&2
        exit 1
    fi
    echo "[${NODE_IP}] no vfio NVMe devices remain; treat cleanup as done despite missing workdir"
    exit 0
fi

cd "${QEMU_VM_WORKDIR}"
test -x "${QEMU_VFIO_BIND_SCRIPT}" || {
    echo "QEMU vfio bind script not found or not executable: ${QEMU_VM_WORKDIR}/${QEMU_VFIO_BIND_SCRIPT}" >&2
    exit 1
}

# Prefer this build's device list; also reclaim any leftover lists from prior builds,
# then fall back to scanning currently bound vfio NVMe devices.
device_files=( )
for candidate in .jenkins_nvme_${BUILD_NUMBER}_vfio_devices .jenkins_nvme_*_vfio_devices; do
    [ -e "${candidate}" ] || continue
    device_files+=( "${candidate}" )
done

unbind_targets=""
if [ "${#device_files[@]}" -gt 0 ]; then
    while IFS= read -r dev; do
        [ -n "$dev" ] || continue
        case " ${unbind_targets} " in
            *" ${dev} "*) ;;
            *) unbind_targets="${unbind_targets} ${dev}" ;;
        esac
    done < <(cat "${device_files[@]}" 2>/dev/null || true)
fi

used_fallback_scan=0
if [ -z "$(printf '%s' "${unbind_targets}" | tr -d ' ')" ]; then
    echo "[${NODE_IP}] no recorded QEMU vfio devices; scan currently bound vfio NVMe"
    used_fallback_scan=1
    while IFS= read -r dev; do
        [ -n "$dev" ] || continue
        unbind_targets="${unbind_targets} ${dev}"
    done < <(list_vfio_nvme_devices)
fi

if [ -z "$(printf '%s' "${unbind_targets}" | tr -d ' ')" ]; then
    echo "[${NODE_IP}] no QEMU vfio NVMe devices to unbind"
else
    for dev in ${unbind_targets}; do
        if [ "${used_fallback_scan}" = "1" ]; then
            echo "[${NODE_IP}] fallback unbind vfio NVMe PCI device back to host: ${dev}"
        else
            echo "[${NODE_IP}] unbind NVMe PCI device back to host: ${dev}"
        fi
        if ! run_vfio_bind_action unbind "$dev"; then
            unbind_failed=1
        fi
    done
fi

# Clear stale device lists after reclaim attempts so the next run starts clean.
rm -f .jenkins_nvme_*_vfio_devices || true

echo 1 > /sys/bus/pci/rescan || true
sleep 5
nvme list || true

remaining=$(list_vfio_nvme_devices | tr '\n' ' ')
if [ -n "$(printf '%s' "${remaining}" | tr -d ' ')" ]; then
    echo "[${NODE_IP}] ERROR: vfio NVMe devices still bound after cleanup:${remaining}" >&2
    exit 1
fi

if [ "${unbind_failed}" -ne 0 ]; then
    echo "[${NODE_IP}] some vfio unbind commands failed, but no vfio NVMe devices remain bound"
fi
HOST_CLEANUP
