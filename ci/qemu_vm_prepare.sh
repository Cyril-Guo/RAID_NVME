#!/bin/bash
set -euo pipefail

: "${NODE_IP:?NODE_IP is required}"
: "${TARGET_USER:?TARGET_USER is required}"
: "${QEMU_VM_PASSWORD:?QEMU_VM_PASSWORD is required}"
: "${QEMU_VM_SSH_PORT:?QEMU_VM_SSH_PORT is required}"
: "${QEMU_VM_WORKDIR:?QEMU_VM_WORKDIR is required}"
: "${QEMU_VM_START_SCRIPT:?QEMU_VM_START_SCRIPT is required}"
: "${QEMU_VFIO_BIND_SCRIPT:?QEMU_VFIO_BIND_SCRIPT is required}"
: "${RAID_CLI_DPRAID_PATH_FOR_RUN:?RAID_CLI_DPRAID_PATH_FOR_RUN is required}"
: "${BUILD_NUMBER:?BUILD_NUMBER is required}"

SSH_OPTS=${SSH_OPTS:-}

host_ssh() {
    ssh ${SSH_OPTS} "${TARGET_USER}@${NODE_IP}" "$@"
}

qemu_ssh() {
    sshpass -p "${QEMU_VM_PASSWORD}" ssh ${SSH_OPTS} -p "${QEMU_VM_SSH_PORT}" "${TARGET_USER}@${NODE_IP}" "$@"
}

echo "[${NODE_IP}] start QEMU VM for automatic MR test"
if ! command -v sshpass >/dev/null 2>&1; then
    echo "[${NODE_IP}] sshpass is missing on Jenkins server, try to install it automatically."
    if command -v apt-get >/dev/null 2>&1; then
        sudo apt-get -o DPkg::Lock::Timeout=600 update
        sudo apt-get -o DPkg::Lock::Timeout=600 install -y sshpass
    elif command -v dnf >/dev/null 2>&1; then
        sudo dnf install -y sshpass
    elif command -v yum >/dev/null 2>&1; then
        sudo yum install -y sshpass
    elif command -v zypper >/dev/null 2>&1; then
        sudo zypper install -y sshpass
    fi
fi
command -v sshpass >/dev/null 2>&1 || {
    echo "sshpass is required on Jenkins server for QEMU VM login, and automatic install failed"
    exit 1
}

if qemu_ssh 'echo qemu vm already running' >/dev/null 2>&1; then
    echo "[${NODE_IP}] QEMU VM is already running, skip vfio bind and ${QEMU_VM_START_SCRIPT}"
else
    scp ${SSH_OPTS} "${RAID_CLI_DPRAID_PATH_FOR_RUN}" "${TARGET_USER}@${NODE_IP}:/tmp/dpraid_${BUILD_NUMBER}_host_prepare"
    host_ssh "NODE_IP='${NODE_IP}' BUILD_NUMBER='${BUILD_NUMBER}' QEMU_VM_WORKDIR='${QEMU_VM_WORKDIR}' QEMU_VFIO_BIND_SCRIPT='${QEMU_VFIO_BIND_SCRIPT}' bash -s" <<'HOST_PREPARE'
set -euo pipefail
install -m 0755 "/tmp/dpraid_${BUILD_NUMBER}_host_prepare" /usr/bin/dpraid
rm -f "/tmp/dpraid_${BUILD_NUMBER}_host_prepare"

echo "[${NODE_IP}] restore physical host RAID state before QEMU handoff"
vd_ids=$(
    dpraid /c0/vall show 2>/dev/null |
    while read -r first rest; do
        case "$first" in
            */*)
                vd="${first#*/}"
                case "$vd" in
                    ""|*[!0-9]*) ;;
                    *) printf "%s\n" "$vd" ;;
                esac
                ;;
        esac
    done | sort -n -u || true
)
for vd in $vd_ids; do
    echo "[${NODE_IP}] delete existing VD before QEMU handoff: v${vd}"
    dpraid "/c0/v${vd}" delete || true
done

slot_ids=$(
    dpraid /c0/eall/sall show 2>/dev/null |
    while read -r first rest; do
        case "$first" in
            *:*)
                slot="${first#*:}"
                case "$slot" in
                    ""|*[!0-9]*) ;;
                    *) printf "%s\n" "$slot" ;;
                esac
                ;;
        esac
    done | sort -n -u || true
)
for slot in $slot_ids; do
    echo "[${NODE_IP}] release physical disk before QEMU handoff: s${slot}"
    dpraid "/c0/eall/s${slot}" delete || true
done

echo 1 > /sys/bus/pci/rescan || true
sleep 5
nvme list || true

cd "${QEMU_VM_WORKDIR}"
test -x "${QEMU_VFIO_BIND_SCRIPT}" || {
    echo "QEMU vfio bind script not found or not executable: ${QEMU_VM_WORKDIR}/${QEMU_VFIO_BIND_SCRIPT}" >&2
    exit 1
}

protected_names=$(
    {
        findmnt -nvo SOURCE / /boot /boot/efi 2>/dev/null || true
        lsblk -nP -o NAME,PKNAME,MOUNTPOINT 2>/dev/null |
            while read -r lsblk_line; do
                NAME=""
                PKNAME=""
                MOUNTPOINT=""
                eval "$lsblk_line"
                if [ -n "$MOUNTPOINT" ]; then
                    printf "/dev/%s\n" "$NAME"
                    [ -n "$PKNAME" ] && printf "/dev/%s\n" "$PKNAME"
                fi
            done
    } |
    while read -r source; do
        [ -n "$source" ] || continue
        source="${source#/dev/}"
        printf "%s\n" "$source"
        pk=$(lsblk -npo PKNAME "/dev/$source" 2>/dev/null | sed "s#^/dev/##" || true)
        [ -n "$pk" ] && printf "%s\n" "$pk"
    done | sort -u
)

vfio_devices=""
for ctrl_path in /sys/class/nvme/nvme*; do
    [ -e "$ctrl_path" ] || continue
    ctrl=$(basename "$ctrl_path")
    bdf=$(basename "$(readlink -f "$ctrl_path/device")")
    skip=0
    for ns_path in "$ctrl_path"/nvme*n*; do
        [ -e "$ns_path" ] || continue
        ns=$(basename "$ns_path")
        pk=$(lsblk -npo PKNAME "/dev/$ns" 2>/dev/null | sed "s#^/dev/##" || true)
        for protected in $protected_names; do
            if [ "$ns" = "$protected" ] || [ "$pk" = "$protected" ] || [ "$ctrl" = "$protected" ]; then
                skip=1
            fi
        done
    done
    if [ "$skip" = "1" ]; then
        echo "[${NODE_IP}] keep system NVMe on host: ${ctrl} ${bdf}"
        continue
    fi
    vfio_devices="${vfio_devices} ${bdf}"
done

if [ -z "$(printf "%s" "$vfio_devices" | tr -d " ")" ]; then
    echo "[${NODE_IP}] no non-system NVMe PCI devices found for QEMU vfio bind"
    : > ".jenkins_nvme_${BUILD_NUMBER}_vfio_devices"
else
    printf "%s\n" $vfio_devices > ".jenkins_nvme_${BUILD_NUMBER}_vfio_devices"
    for dev in $vfio_devices; do
        echo "[${NODE_IP}] bind NVMe PCI device to QEMU vfio: ${dev}"
        DEV="$dev" "${QEMU_VFIO_BIND_SCRIPT}" bind
    done
fi
HOST_PREPARE

    host_ssh "NODE_IP='${NODE_IP}' QEMU_VM_WORKDIR='${QEMU_VM_WORKDIR}' QEMU_VM_START_SCRIPT='${QEMU_VM_START_SCRIPT}' bash -s" <<'HOST_START'
set -euo pipefail
cd "${QEMU_VM_WORKDIR}"
"${QEMU_VM_START_SCRIPT}"
sleep 2
if ! pgrep -f "qemu-system-x86_64.*vm-serial.log" >/dev/null 2>&1; then
    echo "[${NODE_IP}] QEMU process is not running after ${QEMU_VM_START_SCRIPT}; startup failed before SSH wait" >&2
    exit 1
fi
HOST_START

    echo "[${NODE_IP}] wait 60s for QEMU VM boot"
    sleep 60
fi

for attempt in $(seq 1 24); do
    if qemu_ssh 'echo qemu vm ssh ready' >/dev/null 2>&1; then
        echo "[${NODE_IP}] QEMU VM SSH is ready"
        exit 0
    fi
    if ! host_ssh 'pgrep -f "qemu-system-x86_64.*vm-serial.log" >/dev/null 2>&1'; then
        echo "[${NODE_IP}] QEMU process exited before SSH became ready; stop waiting and fail startup" >&2
        exit 1
    fi
    echo "[${NODE_IP}] waiting for QEMU VM SSH, attempt ${attempt}/24"
    sleep 5
done

echo "[${NODE_IP}] QEMU VM SSH is not ready after wait" >&2
exit 1
