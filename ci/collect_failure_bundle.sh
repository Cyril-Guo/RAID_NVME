#!/usr/bin/env bash
# Collect a developer-usable failure bundle on the DUT:
#   - gcore of still-living userspace fio / dpraid processes (primary)
#   - snapshot of draid kernel threads (cannot gcore; stacks/status instead)
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

# Ensure ptrace_scope / ulimit allow gcore before we try to attach.
if [ -f "${SCRIPT_DIR}/enable_failure_coredumps.sh" ]; then
    chmod +x "${SCRIPT_DIR}/enable_failure_coredumps.sh" 2>/dev/null || true
    NODE_IP="${NODE_IP}" REMOTE_DIR="${REMOTE_DIR}" \
        bash "${SCRIPT_DIR}/enable_failure_coredumps.sh" >/dev/null 2>&1 || true
fi

mkdir -p "${WORK_DIR}/cores" "${WORK_DIR}/cores/existing" "${WORK_DIR}/binaries" \
    "${WORK_DIR}/logs" "${WORK_DIR}/draid_kthreads" "${CORE_PATTERN_DIR}"
cd "${WORK_DIR}" || exit 0

{
    echo "Failure bundle for developer gdb / triage"
    echo "NODE_IP=${NODE_IP}"
    echo "RUN_KEY=${RUN_KEY}"
    echo "REASON=${BUNDLE_REASON}"
    echo "HOST=$(hostname 2>/dev/null || true)"
    echo "TIME=$(date -Is 2>/dev/null || date)"
    echo "UID=$(id -u 2>/dev/null || true) USER=$(id -un 2>/dev/null || true)"
    if [ -r /proc/sys/kernel/yama/ptrace_scope ]; then
        echo "ptrace_scope=$(cat /proc/sys/kernel/yama/ptrace_scope 2>/dev/null || true)"
    fi
    echo
    echo "How to inspect userspace gcore dumps:"
    echo "  tar -xzf $(basename "${ARCHIVE}")"
    echo "  gdb binaries/fio cores/core.fio.<pid>"
    echo "  gdb binaries/dpraid cores/core.dpraid.<pid>"
    echo
    echo "NOTE: [draid-*] / [draid_io_retry] etc. are kernel threads (PPID=2)."
    echo "      gcore cannot dump them; see draid_kthreads/ for stacks/status."
    echo "      Point-in-time driver state: draid_diag/ (dpraid show*, sysfs/debugfs)."
    echo "      Full kernel memory needs kdump/vmcore (out of this bundle)."
    echo
    echo "Also see: dmesg.txt, dpraid_*.txt, versions.txt, draid.ko, logs/"
} >README.txt

: >gcore_errors.txt
: >gcore_pids.txt

is_kernel_thread() {
    local pid="$1"
    # Only classify when /proc/<pid> exists. Missing proc means "already gone"
    # or non-Linux test hosts — let the caller decide whether to try gcore.
    [ -d "/proc/${pid}" ] || return 1
    # No userspace exe => kernel thread.
    if [ ! -e "/proc/${pid}/exe" ]; then
        return 0
    fi
    if ! readlink "/proc/${pid}/exe" >/dev/null 2>&1; then
        return 0
    fi
    return 1
}

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
        case "${name}" in
            fio) pids=$(pgrep -f '[f]io' 2>/dev/null || true) ;;
            dpraid) pids=$(pgrep -f '[d]praid' 2>/dev/null || true) ;;
        esac
    fi
    printf '%s\n' "${pids}"
}

run_gcore_one() {
    local name="$1"
    local pid="$2"
    if command -v sudo >/dev/null 2>&1; then
        sudo -n gcore -o "cores/core.${name}" "${pid}" >>gcore_errors.txt 2>&1 && return 0
    fi
    gcore -o "cores/core.${name}" "${pid}" >>gcore_errors.txt 2>&1
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
        if is_kernel_thread "${pid}"; then
            echo "skip kernel thread ${name} pid=${pid} (use draid_kthreads/)" >>gcore_errors.txt
            continue
        fi
        if [ ! -d "/proc/${pid}" ]; then
            echo "${name} pid=${pid} has no /proc entry; still attempting gcore" >>gcore_errors.txt
        fi
        echo "${name} ${pid}" >>gcore_pids.txt
        copy_binary_for_pid "${pid}" "${name}"
        log "gcore ${name} pid=${pid}"
        if ! run_gcore_one "${name}" "${pid}"; then
            echo "gcore failed for ${name} pid=${pid}" >>gcore_errors.txt
        fi
    done
}

snapshot_draid_kernel_threads() {
    local out="draid_kthreads"
    {
        echo "=== ps (draid) ==="
        ps -ef | grep -i '[d]raid' || true
        echo
        echo "=== /proc/modules ==="
        grep -i draid /proc/modules 2>/dev/null || true
    } >"${out}/overview.txt"

    : >"${out}/kernel_threads.txt"
    : >"${out}/userspace.txt"

    local pid comm
    while read -r pid comm; do
        [ -n "${pid}" ] || continue
        case "${comm}" in
            *draid*|*draid_*) ;;
            *) continue ;;
        esac
        # Do not treat the userspace CLI "dpraid" as kernel draid.
        if [ "${comm}" = "dpraid" ]; then
            continue
        fi
        mkdir -p "${out}/pid_${pid}"
        printf '%s\n' "${comm}" >"${out}/pid_${pid}/comm.txt"
        {
            echo "pid=${pid} comm=${comm}"
            echo "=== status ==="
            cat "/proc/${pid}/status" 2>/dev/null || true
            echo
            echo "=== stack ==="
            cat "/proc/${pid}/stack" 2>/dev/null || true
            echo
            echo "=== wchan ==="
            cat "/proc/${pid}/wchan" 2>/dev/null || true
            echo
            echo "=== cmdline ==="
            tr '\0' ' ' <"/proc/${pid}/cmdline" 2>/dev/null; echo
        } >"${out}/pid_${pid}/snapshot.txt" 2>/dev/null || true

        if is_kernel_thread "${pid}"; then
            echo "kernel_thread pid=${pid} comm=${comm}" >>"${out}/kernel_threads.txt"
        else
            echo "userspace pid=${pid} comm=${comm}" >>"${out}/userspace.txt"
            if command -v gcore >/dev/null 2>&1 && [ -d "/proc/${pid}" ]; then
                echo "draid ${pid}" >>gcore_pids.txt
                copy_binary_for_pid "${pid}" "draid"
                log "gcore draid(userspace) pid=${pid}"
                run_gcore_one "draid" "${pid}" \
                    || echo "gcore failed for draid pid=${pid}" >>gcore_errors.txt
            fi
        fi
    done < <(ps -eo pid=,comm= 2>/dev/null | awk 'tolower($0) ~ /draid/ {print $1, $2}')
}

run_gcore fio
run_gcore dpraid
snapshot_draid_kernel_threads

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
    echo
    echo "=== ptrace_scope ==="
    cat /proc/sys/kernel/yama/ptrace_scope 2>/dev/null || echo "n/a"
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

snapshot_draid_driver_state() {
    # Point-in-time driver/controller diagnostics (not full kernel RAM).
    # Best-effort: unsupported CLI subcommands are recorded and ignored.
    local out="draid_diag"
    mkdir -p "${out}/sysfs" "${out}/debugfs" "${out}/proc" "${out}/dpraid"

    safe_run "${out}/dpraid/help.txt" dpraid --help
    safe_run "${out}/dpraid/c0_show.txt" dpraid /c0 show
    safe_run "${out}/dpraid/c0_show_all.txt" dpraid /c0 show all
    safe_run "${out}/dpraid/vall_show_all.txt" dpraid /c0/vall show all
    safe_run "${out}/dpraid/pds_show_all.txt" dpraid /c0/eall/sall show all
    safe_run "${out}/dpraid/events.txt" dpraid /c0 show events
    safe_run "${out}/dpraid/eventlog.txt" dpraid /c0 show eventlog
    safe_run "${out}/dpraid/alarm.txt" dpraid /c0 show alarm
    safe_run "${out}/dpraid/termlog.txt" dpraid /c0 show termlog

    # Per-VD detail when IDs are parseable from vall show.
    local vid
    for vid in $(
        sed -n 's#.*/c0/v\([0-9][0-9]*\).*#\1#p; s/.*\([0-9][0-9]*\)\/\([0-9][0-9]*\).*/\2/p' dpraid_vall.txt 2>/dev/null \
            | grep -E '^[0-9]+$' | sort -n | uniq | head -n 32
    ); do
        [ -n "${vid}" ] || continue
        safe_run "${out}/dpraid/v${vid}_show.txt" dpraid "/c0/v${vid}" show
        safe_run "${out}/dpraid/v${vid}_show_all.txt" dpraid "/c0/v${vid}" show all
    done

    # Module parameters / holders.
    if [ -d /sys/module/draid ]; then
        cp -a /sys/module/draid/parameters "${out}/sysfs/module_parameters" 2>/dev/null || true
        ls -la /sys/module/draid >"${out}/sysfs/module_listing.txt" 2>/dev/null || true
        cat /sys/module/draid/refcnt >"${out}/sysfs/refcnt.txt" 2>/dev/null || true
    fi

    # Discover draid-related sysfs nodes (depth-limited).
    {
        echo "=== find /sys *draid* ==="
        find /sys -maxdepth 6 \( -iname '*draid*' -o -iname '*dpraid*' \) 2>/dev/null | head -n 200
    } >"${out}/sysfs/find.txt"

    # Copy small text files under matched sysfs paths.
    find /sys -maxdepth 6 \( -iname '*draid*' -o -iname '*dpraid*' \) -type f 2>/dev/null \
        | head -n 80 | while read -r f; do
        size=$(wc -c <"$f" 2>/dev/null || echo 999999)
        if [ "${size}" -le 1048576 ] 2>/dev/null; then
            rel=$(echo "$f" | sed 's#^/sys/##; s#[^A-Za-z0-9._/-]#_#g')
            mkdir -p "${out}/sysfs/tree/$(dirname "${rel}")"
            cp -f "$f" "${out}/sysfs/tree/${rel}" 2>/dev/null || true
        fi
    done

    # debugfs (may need mount).
    if [ ! -d /sys/kernel/debug ]; then
        mkdir -p /sys/kernel/debug 2>/dev/null || true
    fi
    if ! mountpoint -q /sys/kernel/debug 2>/dev/null; then
        mount -t debugfs debugfs /sys/kernel/debug 2>/dev/null || true
    fi
    {
        echo "=== find debugfs *draid* ==="
        find /sys/kernel/debug -maxdepth 5 \( -iname '*draid*' -o -iname '*dpraid*' \) 2>/dev/null | head -n 200
    } >"${out}/debugfs/find.txt"
    find /sys/kernel/debug -maxdepth 5 \( -iname '*draid*' -o -iname '*dpraid*' \) -type f 2>/dev/null \
        | head -n 80 | while read -r f; do
        size=$(wc -c <"$f" 2>/dev/null || echo 999999)
        if [ "${size}" -le 2097152 ] 2>/dev/null; then
            rel=$(echo "$f" | sed 's#^/sys/kernel/debug/##; s#[^A-Za-z0-9._/-]#_#g')
            mkdir -p "${out}/debugfs/tree/$(dirname "${rel}")"
            cp -f "$f" "${out}/debugfs/tree/${rel}" 2>/dev/null || true
        fi
    done

    # /proc entries.
    {
        echo "=== /proc *draid* ==="
        ls -la /proc/*draid* /proc/*dpraid* 2>/dev/null || true
    } >"${out}/proc/listing.txt"
    for f in /proc/*draid* /proc/*dpraid*; do
        [ -e "$f" ] || continue
        if [ -f "$f" ]; then
            size=$(wc -c <"$f" 2>/dev/null || echo 999999)
            if [ "${size}" -le 2097152 ] 2>/dev/null; then
                cp -f "$f" "${out}/proc/$(basename "$f")" 2>/dev/null || true
            fi
        elif [ -d "$f" ]; then
            find "$f" -type f -size -2M 2>/dev/null | head -n 40 | while read -r pf; do
                rel=$(echo "$pf" | sed "s#^${f}/##; s#[^A-Za-z0-9._/-]#_#g")
                mkdir -p "${out}/proc/$(basename "$f")/$(dirname "${rel}")"
                cp -f "$pf" "${out}/proc/$(basename "$f")/${rel}" 2>/dev/null || true
            done
        fi
    done

    {
        echo "draid_diag collected at $(date -Is 2>/dev/null || date)"
        echo "contents:"
        find "${out}" -type f 2>/dev/null | head -n 200
    } >"${out}/INDEX.txt"
}

snapshot_draid_driver_state

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
    echo "DRAID_KERNEL_THREADS:"
    cat draid_kthreads/kernel_threads.txt 2>/dev/null || true
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

# Short summary for Allure text attachment (visible without unpacking tar).
{
    echo "NODE_IP=${NODE_IP}"
    echo "RUN_KEY=${RUN_KEY}"
    echo "REASON=${BUNDLE_REASON}"
    echo "ARCHIVE=$(basename "${ARCHIVE}")"
    echo "UID=$(id -u 2>/dev/null || true) USER=$(id -un 2>/dev/null || true)"
    if [ -r /proc/sys/kernel/yama/ptrace_scope ]; then
        echo "ptrace_scope=$(cat /proc/sys/kernel/yama/ptrace_scope 2>/dev/null || true)"
    fi
    echo
    echo "=== gcore_pids (userspace only) ==="
    cat gcore_pids.txt 2>/dev/null || echo "(none)"
    echo
    echo "=== draid kernel threads (not gcore-able) ==="
    cat draid_kthreads/kernel_threads.txt 2>/dev/null || echo "(none)"
    echo
    echo "=== gcore_errors ==="
    cat gcore_errors.txt 2>/dev/null || echo "(none)"
    echo
    if [ ! -s gcore_pids.txt ]; then
        echo "NOTE: no live userspace fio/dpraid when gcore ran."
        echo "FIO stage abort / keyword failures usually exit first, so userspace core is empty."
    fi
    echo "NOTE: [draid-*] kernel threads are snapshotted under draid_kthreads/ (stack/status)."
    echo "NOTE: point-in-time driver state under draid_diag/ (dpraid/sysfs/debugfs; not full RAM)."
    echo "Bundle still includes dmesg, dpraid show, binaries, logs for triage."
} >"${BUNDLE_ROOT}/latest_bundle_summary.txt"

exit 0
