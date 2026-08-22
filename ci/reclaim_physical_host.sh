#!/usr/bin/env bash
# Run on the physical host before CSD flash clear.
# Ensure no QEMU guest owns NVMe: stop VM if running, unload draid, unbind vfio
# devices back to the host so flash clear sees physical controllers.
set -euo pipefail

NODE_IP=${NODE_IP:-unknown}
QEMU_VM_WORKDIR=${QEMU_VM_WORKDIR:-/root/Cyril/qemu}
QEMU_VFIO_BIND_SCRIPT=${QEMU_VFIO_BIND_SCRIPT:-./vfio-bind.sh}
QEMU_VM_PASSWORD=${QEMU_VM_PASSWORD:-123456}
QEMU_VM_SSH_PORT=${QEMU_VM_SSH_PORT:-2233}
TARGET_USER=${TARGET_USER:-root}
VFIO_BIND_TIMEOUT_SECONDS=${VFIO_BIND_TIMEOUT_SECONDS:-30}
BUILD_NUMBER=${BUILD_NUMBER:-0}

echo "[${NODE_IP}] ===== reclaim physical host from QEMU/draid ====="

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

qemu_guest_reachable() {
    if ! command -v sshpass >/dev/null 2>&1; then
        return 1
    fi
    SSHPASS="${QEMU_VM_PASSWORD}" sshpass -e ssh \
        -o StrictHostKeyChecking=no \
        -o UserKnownHostsFile=/dev/null \
        -o ConnectTimeout=3 \
        -p "${QEMU_VM_SSH_PORT}" \
        "${TARGET_USER}@127.0.0.1" 'true' >/dev/null 2>&1
}

stop_qemu_vm_if_running() {
    local qemu_pids
    local attempt
    local still_running
    local qemu_pid

    if qemu_guest_reachable; then
        echo "[${NODE_IP}] QEMU guest SSH is up on port ${QEMU_VM_SSH_PORT}; request poweroff"
        SSHPASS="${QEMU_VM_PASSWORD}" sshpass -e ssh \
            -o StrictHostKeyChecking=no \
            -o UserKnownHostsFile=/dev/null \
            -o ConnectTimeout=5 \
            -p "${QEMU_VM_SSH_PORT}" \
            "${TARGET_USER}@127.0.0.1" \
            'sync; nohup sh -c "sleep 1; poweroff" >/dev/null 2>&1 &' >/dev/null 2>&1 || true
        for attempt in $(seq 1 30); do
            if qemu_guest_reachable; then
                echo "[${NODE_IP}] waiting for QEMU guest shutdown, attempt ${attempt}/30"
                sleep 2
            else
                echo "[${NODE_IP}] QEMU guest SSH is down"
                break
            fi
        done
    else
        echo "[${NODE_IP}] QEMU guest SSH not reachable on port ${QEMU_VM_SSH_PORT}"
    fi

    qemu_pids=$(pgrep -f "qemu-system-x86_64.*vm-serial.log" || true)
    if [ -z "${qemu_pids}" ]; then
        echo "[${NODE_IP}] no QEMU process found on host"
        return 0
    fi

    echo "[${NODE_IP}] force stop QEMU processes on host: ${qemu_pids}"
    kill ${qemu_pids} >/dev/null 2>&1 || true
    for attempt in $(seq 1 15); do
        still_running=""
        for qemu_pid in ${qemu_pids}; do
            kill -0 "${qemu_pid}" >/dev/null 2>&1 && still_running="${still_running} ${qemu_pid}" || true
        done
        [ -z "${still_running}" ] && break
        echo "[${NODE_IP}] waiting for QEMU process exit, attempt ${attempt}/15:${still_running}"
        sleep 2
    done
    for qemu_pid in ${qemu_pids}; do
        kill -0 "${qemu_pid}" >/dev/null 2>&1 && kill -9 "${qemu_pid}" >/dev/null 2>&1 || true
    done

    if pgrep -f "qemu-system-x86_64.*vm-serial.log" >/dev/null 2>&1; then
        echo "[${NODE_IP}] ERROR: QEMU process still running after stop attempts" >&2
        pgrep -af "qemu-system-x86_64" >&2 || true
        exit 1
    fi
    echo "[${NODE_IP}] QEMU processes stopped"
}

unload_draid_module() {
    local candidate
    local found=0

    echo "[${NODE_IP}] unload draid kernel module if loaded"
    for candidate in draid; do
        if grep -q "^${candidate} " /proc/modules; then
            found=1
            rmmod "${candidate}" || modprobe -r "${candidate}" || true
        fi
    done
    # Also try names reported by any local draid.ko if present.
    if [ -f "${DRAID_DIR:-}/draid.ko" ]; then
        candidate=$(modinfo -F name "${DRAID_DIR}/draid.ko" 2>/dev/null || true)
        if [ -n "${candidate}" ] && grep -q "^${candidate} " /proc/modules; then
            found=1
            rmmod "${candidate}" || modprobe -r "${candidate}" || true
        fi
    fi

    if grep -E -q '^(draid) ' /proc/modules; then
        echo "[${NODE_IP}] ERROR: draid module still loaded after remove" >&2
        grep -i draid /proc/modules >&2 || true
        exit 1
    fi
    if [ "${found}" = "1" ]; then
        echo "[${NODE_IP}] draid module unloaded"
    else
        echo "[${NODE_IP}] draid module was not loaded"
    fi
}

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

unbind_vfio_nvme_to_host() {
    local unbind_failed=0
    local used_fallback_scan=0
    local unbind_targets=""
    local device_files=()
    local candidate
    local dev
    local remaining

    if [ ! -d "${QEMU_VM_WORKDIR}" ]; then
        echo "[${NODE_IP}] QEMU workdir not found: ${QEMU_VM_WORKDIR}"
        remaining=$(list_vfio_nvme_devices | tr '\n' ' ')
        if [ -n "$(printf '%s' "${remaining}" | tr -d ' ')" ]; then
            echo "[${NODE_IP}] ERROR: vfio NVMe still bound without workdir/bind script:${remaining}" >&2
            exit 1
        fi
        echo "[${NODE_IP}] no vfio NVMe devices remain; host reclaim done"
        return 0
    fi

    cd "${QEMU_VM_WORKDIR}"
    if [ ! -x "${QEMU_VFIO_BIND_SCRIPT}" ]; then
        if [ -f "${QEMU_VFIO_BIND_SCRIPT}" ]; then
            chmod +x "${QEMU_VFIO_BIND_SCRIPT}" || true
        fi
    fi
    if [ ! -x "${QEMU_VFIO_BIND_SCRIPT}" ]; then
        remaining=$(list_vfio_nvme_devices | tr '\n' ' ')
        if [ -n "$(printf '%s' "${remaining}" | tr -d ' ')" ]; then
            echo "[${NODE_IP}] ERROR: vfio bind script missing and devices still bound:${remaining}" >&2
            exit 1
        fi
        echo "[${NODE_IP}] vfio bind script missing but no vfio NVMe bound; continue"
        return 0
    fi

    for candidate in .jenkins_nvme_${BUILD_NUMBER}_vfio_devices .jenkins_nvme_*_vfio_devices; do
        [ -e "${candidate}" ] || continue
        device_files+=( "${candidate}" )
    done

    if [ "${#device_files[@]}" -gt 0 ]; then
        while IFS= read -r dev; do
            [ -n "$dev" ] || continue
            case " ${unbind_targets} " in
                *" ${dev} "*) ;;
                *) unbind_targets="${unbind_targets} ${dev}" ;;
            esac
        done < <(cat "${device_files[@]}" 2>/dev/null || true)
    fi

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

    rm -f .jenkins_nvme_*_vfio_devices || true

    echo 1 > /sys/bus/pci/rescan || true
    sleep 5
    nvme list || true

    remaining=$(list_vfio_nvme_devices | tr '\n' ' ')
    if [ -n "$(printf '%s' "${remaining}" | tr -d ' ')" ]; then
        echo "[${NODE_IP}] ERROR: vfio NVMe devices still bound after reclaim:${remaining}" >&2
        exit 1
    fi
    if [ "${unbind_failed}" -ne 0 ]; then
        echo "[${NODE_IP}] some vfio unbind commands failed, but no vfio NVMe remain bound"
    fi
    echo "[${NODE_IP}] all NVMe devices returned to physical host"
}

stop_qemu_vm_if_running
unload_draid_module
unbind_vfio_nvme_to_host

echo "[${NODE_IP}] ===== reclaim physical host done ====="
