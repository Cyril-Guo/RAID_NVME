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
TARGET_PASSWORD=${TARGET_PASSWORD:-123456}
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

host_ssh() {
    sshpass -p "${TARGET_PASSWORD}" ssh ${SSH_OPTS} "${TARGET_USER}@${NODE_IP}" "$@"
}

qemu_ssh() {
    sshpass -p "${QEMU_VM_PASSWORD}" ssh ${SSH_OPTS} -p "${QEMU_VM_SSH_PORT}" "${TARGET_USER}@${NODE_IP}" "$@"
}

echo "[${NODE_IP}] start QEMU VM for automatic MR test"
chmod +x "${SCRIPT_DIR}/ensure_sshpass.sh"
"${SCRIPT_DIR}/ensure_sshpass.sh"

if qemu_ssh 'echo qemu vm already running' >/dev/null 2>&1; then
    echo "[${NODE_IP}] QEMU VM is still running before fresh start; try to power it off"
    qemu_ssh 'sync; nohup sh -c "sleep 1; poweroff" >/dev/null 2>&1 &' >/dev/null 2>&1 || true
    for attempt in $(seq 1 30); do
        if qemu_ssh 'true' >/dev/null 2>&1; then
            echo "[${NODE_IP}] waiting for stale QEMU VM shutdown, attempt ${attempt}/30"
            sleep 2
        else
            echo "[${NODE_IP}] stale QEMU VM SSH is down"
            break
        fi
    done
    if qemu_ssh 'true' >/dev/null 2>&1; then
        echo "[${NODE_IP}] QEMU VM is still running after pre-test cleanup; refuse to reuse stale VM" >&2
        exit 1
    fi
fi

host_ssh "NODE_IP='${NODE_IP}' bash -s" <<'HOST_STOP_STALE_QEMU'
set -euo pipefail
qemu_pids=$(pgrep -f "qemu-system-x86_64.*vm-serial.log" || true)
if [ -n "${qemu_pids}" ]; then
    echo "[${NODE_IP}] force stop stale QEMU process before fresh start: ${qemu_pids}"
    kill ${qemu_pids} >/dev/null 2>&1 || true
    for attempt in $(seq 1 15); do
        still_running=""
        for qemu_pid in ${qemu_pids}; do
            kill -0 "${qemu_pid}" >/dev/null 2>&1 && still_running="${still_running} ${qemu_pid}" || true
        done
        [ -z "${still_running}" ] && break
        echo "[${NODE_IP}] waiting for stale QEMU process exit before fresh start, attempt ${attempt}/15:${still_running}"
        sleep 2
    done
    for qemu_pid in ${qemu_pids}; do
        kill -0 "${qemu_pid}" >/dev/null 2>&1 && kill -9 "${qemu_pid}" >/dev/null 2>&1 || true
    done
fi
HOST_STOP_STALE_QEMU

    scp ${SSH_OPTS} "${RAID_CLI_DPRAID_PATH_FOR_RUN}" "${TARGET_USER}@${NODE_IP}:/tmp/dpraid_${BUILD_NUMBER}_host_prepare"
    host_ssh "NODE_IP='${NODE_IP}' BUILD_NUMBER='${BUILD_NUMBER}' QEMU_VM_WORKDIR='${QEMU_VM_WORKDIR}' QEMU_VFIO_BIND_SCRIPT='${QEMU_VFIO_BIND_SCRIPT}' bash -s" <<'HOST_PREPARE'
set -euo pipefail
install -m 0755 "/tmp/dpraid_${BUILD_NUMBER}_host_prepare" /usr/bin/dpraid
rm -f "/tmp/dpraid_${BUILD_NUMBER}_host_prepare"

echo "[${NODE_IP}] unload draid module before QEMU handoff if loaded"
if grep -q "^draid " /proc/modules; then
    rmmod draid || modprobe -r draid
fi
if grep -q "^draid " /proc/modules; then
    echo "[${NODE_IP}] draid module is still loaded before QEMU handoff" >&2
    grep -i draid /proc/modules >&2 || true
    exit 1
fi

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

VFIO_BIND_TIMEOUT_SECONDS=${VFIO_BIND_TIMEOUT_SECONDS:-30}

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
        run_vfio_bind_action bind "$dev"
        pci_path="/sys/bus/pci/devices/${dev}"
        driver_path=$(readlink -f "${pci_path}/driver" 2>/dev/null || true)
        driver=${driver_path##*/}
        group_path=$(readlink -f "${pci_path}/iommu_group" 2>/dev/null || true)
        group=${group_path##*/}
        if [ "$driver" != "vfio-pci" ] || [ -z "$group" ] || [ ! -e "/dev/vfio/${group}" ]; then
            echo "[${NODE_IP}] skip invalid QEMU vfio device: ${dev}, driver=${driver:-none}, group=${group:-none}, node=/dev/vfio/${group:-none}"
            run_vfio_bind_action unbind "$dev" || true
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
rm -rf .jenkins_qemu_wrapper_* .jenkins_start_vm_* .jenkins_qemu_start_*
for old_vfio_file in .jenkins_nvme_*_vfio_devices; do
    [ -e "${old_vfio_file}" ] || continue
    [ "${old_vfio_file}" = "${allowed_file}" ] && continue
    rm -f "${old_vfio_file}"
done
mkdir -p "${wrapper_dir}"
patched_start_script=".jenkins_start_vm_${BUILD_NUMBER}.sh"
if [ ! -s "${allowed_file}" ]; then
    echo "[${NODE_IP}] no validated QEMU vfio device list found: ${allowed_file}" >&2
    exit 1
fi
{
    replacing=0
    replaced=0
    passthrough_var=""
    while IFS= read -r line; do
        if [ "${replacing}" = "0" ] && printf '%s\n' "${line}" | grep -Eq '^[[:space:]]*[A-Za-z_][A-Za-z0-9_]*PASSTHROUGH_HOSTS=\('; then
            passthrough_var=$(printf '%s\n' "${line}" | sed -E 's/^[[:space:]]*([A-Za-z_][A-Za-z0-9_]*PASSTHROUGH_HOSTS)=\(.*/\1/')
            echo "[${NODE_IP}] replace ${passthrough_var} in ${QEMU_VM_START_SCRIPT} with current validated BDF list" >&2
            printf '%s\n' "${passthrough_var}=("
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
        echo "[${NODE_IP}] *PASSTHROUGH_HOSTS block not found in ${QEMU_VM_START_SCRIPT}; use original script and rely on QEMU vfio wrapper filtering" >&2
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
seen_vfio_hosts=""
root_port_ids=""
used_vfio_buses=""
while [ "$#" -gt 0 ]; do
    arg="$1"
    shift
    if [ "$arg" = "-device" ] && [ "$#" -gt 0 ]; then
        device_arg="$1"
        shift
        if [[ "$device_arg" == pcie-root-port,* ]]; then
            port_id="${device_arg#*id=}"
            port_id="${port_id%%,*}"
            [ "$port_id" != "$device_arg" ] && root_port_ids="${root_port_ids} ${port_id}"
        fi
        if [[ "$device_arg" == vfio-pci,host=* ]]; then
            bdf="${device_arg#*host=}"
            bdf="${bdf%%,*}"
            bus_id="${device_arg#*bus=}"
            bus_id="${bus_id%%,*}"
            [ "$bus_id" = "$device_arg" ] && bus_id=""
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
            seen_vfio_hosts="${seen_vfio_hosts} ${bdf}"
            [ -n "$bus_id" ] && used_vfio_buses="${used_vfio_buses} ${bus_id}"
        fi
        filtered_args+=("-device" "$device_arg")
        continue
    fi
    filtered_args+=("$arg")
done
next_port=90
while IFS= read -r bdf; do
    [ -n "$bdf" ] || continue
    case " ${seen_vfio_hosts} " in
        *" ${bdf} "*) continue ;;
    esac
    group_path=$(readlink -f "/sys/bus/pci/devices/${bdf}/iommu_group" 2>/dev/null || true)
    group="${group_path##*/}"
    if [ -z "$group" ] || [ ! -e "/dev/vfio/${group}" ]; then
        echo "skip auto QEMU vfio device without vfio node: ${bdf}, group=${group:-none}, node=/dev/vfio/${group:-none}" >&2
        continue
    fi
    echo "append auto detected QEMU vfio device: ${bdf}" >&2
    target_bus=""
    for port_id in $root_port_ids; do
        case " ${used_vfio_buses} " in
            *" ${port_id} "*) ;;
            *) target_bus="$port_id"; break ;;
        esac
    done
    if [ -z "$target_bus" ]; then
        target_bus="autoport${next_port}"
        filtered_args+=("-device" "pcie-root-port,id=${target_bus},chassis=${next_port},bus=pcie.0")
        root_port_ids="${root_port_ids} ${target_bus}"
        next_port=$((next_port + 1))
    fi
    filtered_args+=("-device" "vfio-pci,host=${bdf},bus=${target_bus}")
    used_vfio_buses="${used_vfio_buses} ${target_bus}"
done < "${QEMU_ALLOWED_VFIO_FILE}"
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
    qemu_pids=$(pgrep -f "qemu-system-x86_64.*vm-serial.log" || true)
    if [ -n "${qemu_pids}" ]; then
        for qemu_pid in ${qemu_pids}; do
            qemu_cmdline=$(tr '\000' ' ' < "/proc/${qemu_pid}/cmdline" 2>/dev/null || true)
            missing_bdf=""
            while IFS= read -r bdf; do
                [ -n "${bdf}" ] || continue
                if ! printf '%s\n' "${qemu_cmdline}" | grep -Fq "host=${bdf}"; then
                    missing_bdf="${missing_bdf} ${bdf}"
                fi
            done < "${allowed_file}"
            if [ -z "$(printf '%s' "${missing_bdf}" | tr -d ' ')" ]; then
                echo "[${NODE_IP}] QEMU process is running with validated vfio devices"
                tail -n 80 "${start_log}" || true
                exit 0
            fi
            echo "[${NODE_IP}] QEMU process ${qemu_pid} does not contain current vfio devices:${missing_bdf}" >&2
        done
        tail -n 120 "${start_log}" >&2 || true
        exit 1
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
