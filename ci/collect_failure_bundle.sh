#!/usr/bin/env bash
# Collect a developer-usable failure bundle on the DUT:
#   - gcore of still-living fio / dpraid processes (primary)
#   - matching binaries, draid.ko, dmesg, RAID/NVMe snapshots, recent logs
# Always exits 0 so collection never overrides the original test failure code.
set -uo pipefail

NODE_IP=${NODE_IP:-unknown}
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/.." && pwd)
REMOTE_DIR=${REMOTE_DIR:-${REPO_ROOT}}
RUN_KEY=${RUN_KEY:-unknown}
BUNDLE_REASON=${BUNDLE_REASON:-test_failure}
TS=$(date +%Y%m%d_%H%M%S)
SAFE_IP=${NODE_IP//[^A-Za-z0-9._-]/_}
SAFE_KEY=${RUN_KEY//[^A-Za-z0-9._-]/_}
BUNDLE_ROOT="${REMOTE_DIR}/failure_bundles"
WORK_DIR="${BUNDLE_ROOT}/${TS}_${SAFE_KEY}"
ARCHIVE="${BUNDLE_ROOT}/failure_bundle_${SAFE_IP}_${SAFE_KEY}_${TS}.tar.gz"
CORE_PATTERN_DIR="${REMOTE_DIR}/failure_bundles/cores"

log() {
    printf '[%s] %s\n' "${NODE_IP}" "$*"
}

safe_run() {
    local out="$1"
    shift
    {
        printf '+ '
        printf '%q ' "$@"
        printf '\n'
        "$@" 2>&1
    } >"${out}" 2>&1 || printf 'command failed rc=%s\n' "$?" >>"${out}"
}

mkdir -p "${WORK_DIR}/cores" "${WORK_DIR}/cores/existing" "${WORK_DIR}/binaries" "${WORK_DIR}/logs" "${CORE_PATTERN_DIR}"
cd "${WORK_DIR}" || exit 0

{
    echo "Failure bundle for developer gdb / triage"
    echo "NODE_IP=${NODE_IP}"
    echo "RUN_KEY=${RUN_KEY}"
    echo "REASON=${BUNDLE_REASON}"
    echo "HOST=$(hostname 2>/dev/null || true)"
    echo "TIME=$(date -Is 2>/dev/null || date)"
    echo
    echo "How to inspect gcore dumps:"
    echo "  tar -xzf $(basename "${ARCHIVE}")"
    echo "  gdb binaries/fio cores/core.fio.<pid>"
    echo "  gdb binaries/dpraid cores/core.dpraid.<pid>"
    echo
    echo "Also see: dmesg.txt, dpraid_*.txt, versions.txt, draid.ko, logs/"
} >README.txt

: >gcore_errors.txt
: >gcore_pids.txt

copy_binary_for_pid() {
    local pid="$1"
    local label="$2"
    local exe=""
    if [ -r "/proc/${pid}/exe" ]; then
        exe=$(readlink -f "/proc/${pid}/exe" 2>/dev/null || true)
    fi
    if [ -n "${exe}" ] && [ -f "${exe}" ]; then
        cp -f "${exe}" "binaries/${label}.pid${pid}" 2>>gcore_errors.txt || true
        printf '%s pid=%s exe=%s\n' "${label}" "${pid}" "${exe}" >>binaries/index.txt
        # Keep a stable name for the first copy of each label.
        if [ ! -e "binaries/${label}" ]; then
            cp -f "${exe}" "binaries/${label}" 2>>gcore_errors.txt || true
        fi
    fi
}

gcore_pids_for() {
    local name="$1"
    local pids=""
    pids=$(pgrep -x "${name}" 2>/dev/null || true)
    if [ -z "${pids}" ]; then
        # Fallback: avoid matching the pgrep line itself.
        case "${name}" in
            fio) pids=$(pgrep -f '[f]io' 2>/dev/null || true) ;;
            dpraid) pids=$(pgrep -f '[d]praid' 2>/dev/null || true) ;;
        esac
    fi
    printf '%s\n' "${pids}"
}

run_gcore() {
    local name="$1"
    local pid
    local pids
    pids=$(gcore_pids_for "${name}")
    if [ -z "${pids}" ]; then
        echo "no live ${name} process" >>gcore_errors.txt
        return 0
    fi
    if ! command -v gcore >/dev/null 2>&1; then
        echo "gcore not found (install gdb); skip ${name}" >>gcore_errors.txt
        return 0
    fi
    for pid in ${pids}; do
        [ -n "${pid}" ] || continue
        echo "${name} ${pid}" >>gcore_pids.txt
        copy_binary_for_pid "${pid}" "${name}"
        log "gcore ${name} pid=${pid}"
        if ! gcore -o "cores/core.${name}" "${pid}" >>gcore_errors.txt 2>&1; then
            echo "gcore failed for ${name} pid=${pid}" >>gcore_errors.txt
        fi
    done
}

run_gcore fio
run_gcore dpraid

# Prefer PATH binaries when no process binary was copied.
if [ ! -e binaries/fio ] && command -v fio >/dev/null 2>&1; then
    cp -f "$(command -v fio)" binaries/fio 2>>gcore_errors.txt || true
fi
if [ ! -e binaries/dpraid ]; then
    if [ -x /usr/bin/dpraid ]; then
        cp -f /usr/bin/dpraid binaries/dpraid 2>>gcore_errors.txt || true
    elif command -v dpraid >/dev/null 2>&1; then
        cp -f "$(command -v dpraid)" binaries/dpraid 2>>gcore_errors.txt || true
    fi
fi

{
    echo "=== uname ==="
    uname -a || true
    echo
    echo "=== fio ==="
    (command -v fio; fio --version) 2>&1 || true
    echo
    echo "=== dpraid ==="
    (command -v dpraid; ls -l /usr/bin/dpraid 2>/dev/null; /usr/bin/dpraid --help 2>&1 | head -n 5) 2>&1 || true
    echo
    echo "=== modinfo draid ==="
    modinfo draid 2>&1 || true
    echo
    echo "=== lsmod draid ==="
    lsmod 2>/dev/null | grep -i draid || true
} >versions.txt

DRAID_KO="${REMOTE_DIR}/kernel_driver/drivers/draid/draid.ko"
if [ -f "${DRAID_KO}" ]; then
    cp -f "${DRAID_KO}" ./draid.ko 2>>gcore_errors.txt || true
fi

safe_run dmesg.txt dmesg -T
safe_run dpraid_show.txt dpraid show
safe_run dpraid_vall.txt dpraid /c0/vall show
safe_run dpraid_pds.txt dpraid /c0/eall/sall show
safe_run nvme_list.txt nvme list
safe_run lsblk.txt lsblk -o NAME,SIZE,TYPE,MOUNTPOINT

# Existing cores under workspace / cwd patterns.
find "${REMOTE_DIR}" /tmp /var/lib/systemd/coredump -maxdepth 3 \
    \( -name 'core' -o -name 'core.*' -o -name 'core-*' \) \
    -type f 2>/dev/null | head -n 20 | while read -r corefile; do
    cp -f "${corefile}" "cores/existing/$(basename "${corefile}")" 2>>gcore_errors.txt || true
done

if command -v coredumpctl >/dev/null 2>&1; then
    coredumpctl list 2>/dev/null | tail -n 30 >cores/existing/coredumpctl_list.txt || true
fi

# Recent IO_Stress / case logs (best-effort, size-limited).
copy_log_tree() {
    local src="$1"
    local dst="$2"
    [ -d "${src}" ] || return 0
    mkdir -p "${dst}"
    # Prefer smaller / important dirs; skip huge raw dumps when possible.
    if [ -d "${src}/TestErrorLog" ]; then
        cp -a "${src}/TestErrorLog" "${dst}/" 2>>gcore_errors.txt || true
    fi
    if [ -d "${src}/ResultLog" ]; then
        find "${src}/ResultLog" -type f -size -20M 2>/dev/null | head -n 80 | while read -r f; do
            mkdir -p "${dst}/ResultLog"
            cp -f "$f" "${dst}/ResultLog/" 2>>gcore_errors.txt || true
        done
    fi
    find "${src}" -maxdepth 2 -type f \( -name '*.log' -o -name 'result.log' -o -name '*error*' \) \
        -size -10M 2>/dev/null | head -n 40 | while read -r f; do
        cp -f "$f" "${dst}/$(basename "$f")" 2>>gcore_errors.txt || true
    done
}

copy_log_tree "${REMOTE_DIR}/IO_Stress/log" "logs/IO_Stress_log"
if [ -d "${REMOTE_DIR}/cases" ]; then
    # Prefer the failing run_key case dir when present.
    if [ -d "${REMOTE_DIR}/cases/${RUN_KEY}" ]; then
        copy_log_tree "${REMOTE_DIR}/cases/${RUN_KEY}/IO_Stress/log" "logs/case_${SAFE_KEY}"
    else
        find "${REMOTE_DIR}/cases" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | head -n 3 | while read -r cdir; do
            copy_log_tree "${cdir}/IO_Stress/log" "logs/case_$(basename "${cdir}")"
        done
    fi
fi

meta_file=meta.txt
{
    echo "NODE_IP=${NODE_IP}"
    echo "RUN_KEY=${RUN_KEY}"
    echo "REASON=${BUNDLE_REASON}"
    echo "REMOTE_DIR=${REMOTE_DIR}"
    echo "ARCHIVE=$(basename "${ARCHIVE}")"
    echo "PWD=$(pwd)"
    echo "GCORE_PIDS:"
    cat gcore_pids.txt 2>/dev/null || true
} >"${meta_file}"

# Pack from parent so archive contains a single top-level directory.
parent=$(dirname "${WORK_DIR}")
base=$(basename "${WORK_DIR}")
if tar -C "${parent}" -czf "${ARCHIVE}" "${base}" 2>>gcore_errors.txt; then
    log "failure bundle ready: ${ARCHIVE}"
    printf '%s\n' "${ARCHIVE}" >"${BUNDLE_ROOT}/latest_bundle_path.txt"
else
    log "WARN: failed to create ${ARCHIVE}"
fi

exit 0
