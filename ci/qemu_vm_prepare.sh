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

vfio_candidates=""
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
    vfio_candidates="${vfio_candidates} ${bdf}"
done

if [ -z "$(printf "%s" "$vfio_candidates" | tr -d " ")" ]; then
    echo "[${NODE_IP}] no non-system NVMe PCI devices found for QEMU vfio bind"
    : > ".jenkins_nvme_${BUILD_NUMBER}_vfio_devices"
else
    : > ".jenkins_nvme_${BUILD_NUMBER}_vfio_devices"
    for dev in $vfio_candidates; do
        echo "[${NODE_IP}] bind NVMe PCI device to QEMU vfio: ${dev}"
        DEV="$dev" "${QEMU_VFIO_BIND_SCRIPT}" bind
        pci_path="/sys/bus/pci/devices/${dev}"
        driver_path=$(readlink -f "${pci_path}/driver" 2>/dev/null || true)
        driver=${driver_path##*/}
        group_path=$(readlink -f "${pci_path}/iommu_group" 2>/dev/null || true)
        group=${group_path##*/}
        if [ "$driver" != "vfio-pci" ] || [ -z "$group" ] || [ ! -e "/dev/vfio/${group}" ]; then
            echo "[${NODE_IP}] skip invalid QEMU vfio device: ${dev}, driver=${driver:-none}, group=${group:-none}, node=/dev/vfio/${group:-none}"
            DEV="$dev" "${QEMU_VFIO_BIND_SCRIPT}" unbind || true
            continue
        fi
        printf "%s\n" "$dev" >> ".jenkins_nvme_${BUILD_NUMBER}_vfio_devices"
    done
    if [ ! -s ".jenkins_nvme_${BUILD_NUMBER}_vfio_devices" ]; then
        echo "[${NODE_IP}] no usable QEMU vfio NVMe devices after bind validation"
        exit 1
    fi
fi
HOST_PREPARE

    host_ssh "NODE_IP='${NODE_IP}' BUILD_NUMBER='${BUILD_NUMBER}' QEMU_VM_WORKDIR='${QEMU_VM_WORKDIR}' QEMU_VM_START_SCRIPT='${QEMU_VM_START_SCRIPT}' bash -s" <<'HOST_START'
set -euo pipefail
cd "${QEMU_VM_WORKDIR}"
allowed_file=".jenkins_nvme_${BUILD_NUMBER}_vfio_devices"
real_qemu=$(command -v qemu-system-x86_64)
wrapper_dir=".jenkins_qemu_wrapper_${BUILD_NUMBER}"
mkdir -p "${wrapper_dir}"
patched_start_script=".jenkins_start_vm_${BUILD_NUMBER}.sh"
if [ ! -s "${allowed_file}" ]; then
    echo "[${NODE_IP}] no validated QEMU vfio device list found: ${allowed_file}" >&2
    exit 1
fi
{
    replacing=0
    replaced=0
    while IFS= read -r line; do
        if [ "${replacing}" = "0" ] && printf '%s\n' "${line}" | grep -Eq '^[[:space:]]*PASSTHROUGH_HOSTS=\('; then
            printf '%s\n' 'PASSTHROUGH_HOSTS=('
            while IFS= read -r bdf; do
                [ -n "${bdf}" ] || continue
                printf '  "%s"\n' "${bdf}"
            done < "${allowed_file}"
            printf '%s\n' ')'
            replacing=1
            replaced=1
            continue
        fi
        if [ "${replacing}" = "1" ]; then
            [ "$(printf '%s' "${line}" | tr -d '[:space:]')" = ")" ] && replacing=0
            continue
        fi
        printf '%s\n' "${line}"
    done < "${QEMU_VM_START_SCRIPT}"
    [ "${replaced}" = "1" ] || {
        echo "[${NODE_IP}] PASSTHROUGH_HOSTS block not found in ${QEMU_VM_START_SCRIPT}; use original script and rely on QEMU vfio wrapper filtering" >&2
        cat "${QEMU_VM_START_SCRIPT}"
    }
} > "${patched_start_script}"
chmod +x "${patched_start_script}"
echo "[${NODE_IP}] use auto detected QEMU passthrough hosts from ${allowed_file}:"
cat "${allowed_file}"
cat > "${wrapper_dir}/qemu-system-x86_64" <<'QEMU_WRAPPER'
#!/bin/bash
set -euo pipefail
filtered_args=()
while [ "$#" -gt 0 ]; do
    arg="$1"
    shift
    if [ "$arg" = "-device" ] && [ "$#" -gt 0 ]; then
        device_arg="$1"
        shift
        if [[ "$device_arg" == vfio-pci,host=* ]]; then
            bdf="${device_arg#*host=}"
            bdf="${bdf%%,*}"
            group_path=$(readlink -f "/sys/bus/pci/devices/${bdf}/iommu_group" 2>/dev/null || true)
            group="${group_path##*/}"
            if ! grep -Fxq "$bdf" "${QEMU_ALLOWED_VFIO_FILE}"; then
                echo "skip QEMU vfio device not in validated list: ${bdf}" >&2
                continue
            fi
            if [ -z "$group" ] || [ ! -e "/dev/vfio/${group}" ]; then
                echo "skip QEMU vfio device without vfio node: ${bdf}, group=${group:-none}, node=/dev/vfio/${group:-none}" >&2
                continue
            fi
        fi
        filtered_args+=("-device" "$device_arg")
        continue
    fi
    filtered_args+=("$arg")
done
exec "${QEMU_REAL_BINARY}" "${filtered_args[@]}"
QEMU_WRAPPER
chmod +x "${wrapper_dir}/qemu-system-x86_64"
start_log=".jenkins_qemu_start_${BUILD_NUMBER}.log"
rm -f "${start_log}"
(
    QEMU_REAL_BINARY="${real_qemu}" QEMU_ALLOWED_VFIO_FILE="${PWD}/${allowed_file}" PATH="${PWD}/${wrapper_dir}:$PATH" "./${patched_start_script}"
) >"${start_log}" 2>&1 &
start_pid=$!
for attempt in $(seq 1 30); do
    if pgrep -f "qemu-system-x86_64.*vm-serial.log" >/dev/null 2>&1; then
        echo "[${NODE_IP}] QEMU process is running"
        tail -n 80 "${start_log}" || true
        exit 0
    fi
    if ! kill -0 "${start_pid}" >/dev/null 2>&1; then
        echo "[${NODE_IP}] ${QEMU_VM_START_SCRIPT} exited before QEMU process started" >&2
        tail -n 120 "${start_log}" >&2 || true
        exit 1
    fi
    echo "[${NODE_IP}] waiting for QEMU process, attempt ${attempt}/30"
    sleep 2
done
echo "[${NODE_IP}] QEMU process is not running after ${QEMU_VM_START_SCRIPT}; startup failed before SSH wait" >&2
tail -n 120 "${start_log}" >&2 || true
exit 1
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
