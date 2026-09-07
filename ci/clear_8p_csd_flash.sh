#!/usr/bin/env bash
set -euo pipefail

# Clear CSD flash+cache via dpraid on each target reported by `dpraid show`.
#
# New CLI (v1.6+): ASICs table — column ASIC is the /cX target id (was Ctrl/ID):
#   Ctl ASIC BDF     PCIe slot FW       Status
#   0   0    01:00.0 Slot 4    FH003104 Optimal
#   0   1    02:00.0 Slot 4-1  FH003104 Optimal
#   -> flash-clear /c0 and /c1
#
# Legacy CLI: controller table after CONTROLLER MODEL:
#   ID CONTROLLER MODEL ... SERIAL NUMBER ... NUMA STAT FW_VER DRIVER_VER
#   0  DAPUSTOR ...         SN-...            0    Optimal ...
#   -> /c0 (and /c1 if present)
#
# Important: Jenkins agents often override HOME to the DUT workspace, while
# dpraid typically resolves the passwd home (/root) for job artifacts. Force
# both sides onto /root/.dpraid unless DPRAID_HOME is explicitly set.

NODE_IP=${NODE_IP:-unknown}
DPRAID_BIN=${DPRAID_BIN:-dpraid}

# Align HOME with the account home used by dpraid when running as root.
if [ "$(id -u 2>/dev/null || echo 1)" = "0" ]; then
    export HOME=/root
fi

# Prefer explicit override; otherwise always use /root/.dpraid (not $HOME/.dpraid
# from a Jenkins workspace override).
DPRAID_HOME=${DPRAID_HOME:-/root/.dpraid}
DPRAID_JOBS_DIR=${DPRAID_JOBS_DIR:-"${DPRAID_HOME}/jobs"}
# Fail if free space on the filesystem holding DPRAID_HOME is below this many MiB.
DPRAID_MIN_FREE_MB=${DPRAID_MIN_FREE_MB:-512}
# Also reclaim when inode use is this high (df -h can look fine while creates fail).
DPRAID_MAX_INODE_PCT=${DPRAID_MAX_INODE_PCT:-95}
JENKINS_DUT_ROOT=${JENKINS_DUT_ROOT:-/root/Cyril/Jenkins}
# When reclaiming space, keep this many newest build/physical/restore dirs per branch.
JENKINS_KEEP_BUILDS=${JENKINS_KEEP_BUILDS:-2}

banner() {
    echo ""
    echo "[${NODE_IP}] ========== $* =========="
}

ok() {
    echo "[${NODE_IP}] [OK] $*"
}

fail() {
    echo "[${NODE_IP}] [FAIL] $*" >&2
}

warn() {
    echo "[${NODE_IP}] [WARN] $*"
}

free_mb_for_path() {
    local target="$1"
    local parent="$target"
    while [ ! -e "$parent" ] && [ "$parent" != "/" ]; do
        parent="$(dirname "$parent")"
    done
    df -Pm "$parent" 2>/dev/null | awk 'NR==2 { print $4 + 0 }'
}

disk_use_pct_for_path() {
    local target="$1"
    local parent="$target"
    while [ ! -e "$parent" ] && [ "$parent" != "/" ]; do
        parent="$(dirname "$parent")"
    done
    df -P "$parent" 2>/dev/null | awk 'NR==2 { gsub(/%/, "", $5); print $5 + 0 }'
}

inode_use_pct_for_path() {
    local target="$1"
    local parent="$target"
    while [ ! -e "$parent" ] && [ "$parent" != "/" ]; do
        parent="$(dirname "$parent")"
    done
    df -Pi "$parent" 2>/dev/null | awk 'NR==2 { gsub(/%/, "", $5); print $5 + 0 }'
}

show_disk() {
    local target="$1"
    local parent="$target"
    while [ ! -e "$parent" ] && [ "$parent" != "/" ]; do
        parent="$(dirname "$parent")"
    done
    df -h "$parent" 2>/dev/null || true
    df -i "$parent" 2>/dev/null || true
}

prune_dpraid_jobs() {
    if [ ! -d "${DPRAID_JOBS_DIR}" ]; then
        return 0
    fi
    local count
    count="$(find "${DPRAID_JOBS_DIR}" -mindepth 1 -maxdepth 1 2>/dev/null | wc -l | tr -d ' ')"
    if [ "${count}" = "0" ]; then
        return 0
    fi
    warn "prune old dpraid job dirs under ${DPRAID_JOBS_DIR} (count=${count})"
    # Keep nothing from previous runs; flash-clear creates fresh job dirs.
    find "${DPRAID_JOBS_DIR}" -mindepth 1 -maxdepth 1 -exec rm -rf {} + 2>/dev/null || true
}

prune_old_jenkins_workspaces() {
    if [ ! -d "${JENKINS_DUT_ROOT}" ]; then
        return 0
    fi
    warn "disk/inode low: prune old DUT Jenkins workspaces under ${JENKINS_DUT_ROOT} (keep ${JENKINS_KEEP_BUILDS} newest per kind)"
    # Layout: /root/Cyril/Jenkins/<job>/<branch>/<build|physical|restore>-<N>
    find "${JENKINS_DUT_ROOT}" -mindepth 3 -maxdepth 3 -type d \( \
        -name 'build-*' -o -name 'physical-*' -o -name 'restore-*' \
    \) -printf '%h\t%f\n' 2>/dev/null | awk -F '\t' '
        {
            dir = $1
            name = $2
            n = split(name, parts, "-")
            if (n < 2) next
            kind = parts[1]
            num = parts[n]
            if (num !~ /^[0-9]+$/) next
            key = dir "/" kind
            print key "\t" num "\t" dir "/" name
        }
    ' | sort -t $'\t' -k1,1 -k2,2nr | awk -F '\t' -v keep="${JENKINS_KEEP_BUILDS}" '
        {
            key = $1
            path = $3
            count[key]++
            if (count[key] > keep) {
                print path
            }
        }
    ' | while IFS= read -r old_dir; do
        [ -n "${old_dir}" ] || continue
        echo "[${NODE_IP}] remove old workspace: ${old_dir}"
        rm -rf "${old_dir}" || true
    done
}

probe_dpraid_writable() {
    local probe="${DPRAID_JOBS_DIR}/.write_probe_$$"
    if ! (umask 022; echo ok >"${probe}"); then
        return 1
    fi
    rm -f "${probe}" || true
    return 0
}

ensure_dpraid_workspace() {
    banner "0/2 disk + dpraid workspace preflight"
    echo "[${NODE_IP}] HOME=${HOME:-} USER=$(id -un 2>/dev/null || echo '?') DPRAID_HOME=${DPRAID_HOME}"
    show_disk "${DPRAID_HOME}"

    local free_mb use_pct inode_pct
    free_mb="$(free_mb_for_path "${DPRAID_HOME}")"
    use_pct="$(disk_use_pct_for_path "${DPRAID_HOME}")"
    inode_pct="$(inode_use_pct_for_path "${DPRAID_HOME}")"
    # Normalize to digits only; broken df output must not trip `set -e`/`[` checks.
    free_mb="$(printf '%s' "${free_mb:-0}" | tr -cd '0-9')"
    use_pct="$(printf '%s' "${use_pct:-0}" | tr -cd '0-9')"
    inode_pct="$(printf '%s' "${inode_pct:-0}" | tr -cd '0-9')"
    free_mb=${free_mb:-0}
    use_pct=${use_pct:-0}
    inode_pct=${inode_pct:-0}
    echo "[${NODE_IP}] filesystem for ${DPRAID_HOME}: free=${free_mb}MiB use=${use_pct}% inodes=${inode_pct}%"

    if [ "${use_pct}" -ge 95 ] || [ "${free_mb}" -lt "${DPRAID_MIN_FREE_MB}" ] || [ "${inode_pct}" -ge "${DPRAID_MAX_INODE_PCT}" ]; then
        warn "low disk/inode (need >= ${DPRAID_MIN_FREE_MB}MiB free, inodes < ${DPRAID_MAX_INODE_PCT}%); reclaiming..."
        prune_dpraid_jobs
        prune_old_jenkins_workspaces
        # Also drop common junk that accumulates during stress runs.
        rm -rf /tmp/jenkins_nvme_* 2>/dev/null || true
        sync || true
        show_disk "${DPRAID_HOME}"
        free_mb="$(free_mb_for_path "${DPRAID_HOME}")"
        use_pct="$(disk_use_pct_for_path "${DPRAID_HOME}")"
        inode_pct="$(inode_use_pct_for_path "${DPRAID_HOME}")"
        free_mb="$(printf '%s' "${free_mb:-0}" | tr -cd '0-9')"
        use_pct="$(printf '%s' "${use_pct:-0}" | tr -cd '0-9')"
        inode_pct="$(printf '%s' "${inode_pct:-0}" | tr -cd '0-9')"
        free_mb=${free_mb:-0}
        use_pct=${use_pct:-0}
        inode_pct=${inode_pct:-0}
        echo "[${NODE_IP}] after reclaim: free=${free_mb}MiB use=${use_pct}% inodes=${inode_pct}%"
    fi

    if [ "${free_mb}" -lt "${DPRAID_MIN_FREE_MB}" ]; then
        fail "not enough free disk for dpraid jobs (free=${free_mb}MiB, need >= ${DPRAID_MIN_FREE_MB}MiB)"
        echo "[${NODE_IP}] hint: root FS is nearly full; clean /root/Cyril/Jenkins, /var/log, cores, then retry" >&2
        show_disk "${DPRAID_HOME}" >&2 || true
        exit 1
    fi
    if [ "${inode_pct}" -ge "${DPRAID_MAX_INODE_PCT}" ]; then
        fail "inode use too high for dpraid jobs (inodes=${inode_pct}%, need < ${DPRAID_MAX_INODE_PCT}%)"
        echo "[${NODE_IP}] hint: df -h can look fine while df -i is exhausted; prune many small files" >&2
        show_disk "${DPRAID_HOME}" >&2 || true
        exit 1
    fi

    mkdir -p "${DPRAID_JOBS_DIR}" || {
        fail "cannot create ${DPRAID_JOBS_DIR}"
        echo "[${NODE_IP}] hint: check permissions and free space on $(dirname "${DPRAID_HOME}")" >&2
        exit 1
    }
    # Always drop leftover job dirs so flash-clear does not inherit stale paths.
    prune_dpraid_jobs
    mkdir -p "${DPRAID_JOBS_DIR}"

    # Also ensure the classic /root/.dpraid/jobs when tests override DPRAID_HOME
    # but the real binary still resolves passwd home.
    if [ "${DPRAID_HOME}" != "/root/.dpraid" ] && [ "$(id -u 2>/dev/null || echo 1)" = "0" ]; then
        mkdir -p /root/.dpraid/jobs || true
    fi

    if ! probe_dpraid_writable; then
        fail "cannot write under ${DPRAID_JOBS_DIR}"
        echo "[${NODE_IP}] hint: HOME=${HOME:-} DPRAID_HOME=${DPRAID_HOME}; check mount options (ro?) and permissions" >&2
        ls -la "$(dirname "${DPRAID_JOBS_DIR}")" >&2 || true
        exit 1
    fi
    ok "dpraid workspace ready: ${DPRAID_JOBS_DIR} (free=${free_mb}MiB inodes=${inode_pct}%)"
}

is_dpraid_workspace_error() {
    local text="$1"
    printf '%s\n' "${text}" | grep -qiE \
        'Could not open file for writing|No such file or directory.*\.dpraid|\.dpraid/jobs/.*/results'
}

run_dpraid() {
    # Keep HOME pinned so job artifacts land under the prepared workspace.
    HOME="${HOME}" "${DPRAID_BIN}" "$@"
}

if ! command -v "${DPRAID_BIN}" >/dev/null 2>&1 && [ ! -x "${DPRAID_BIN}" ]; then
    fail "dpraid command not found (PATH=${PATH})"
    exit 1
fi

banner "CSD flash+cache clear (dpraid)"
echo "[${NODE_IP}] plan: disk check -> dpraid show -> flash-clear --with-cache --force on each /cX"

ensure_dpraid_workspace

banner "1/2 dpraid show (discover controllers)"
echo "[${NODE_IP}] cmd: ${DPRAID_BIN} show (HOME=${HOME})"
set +e
show_output="$(run_dpraid show 2>&1)"
show_rc=$?
set -e
printf '%s\n' "${show_output}"
if [ "${show_rc}" -ne 0 ]; then
    fail "dpraid show failed (rc=${show_rc})"
    echo "[${NODE_IP}] hint: is dpraid installed and draid loaded?" >&2
    exit 1
fi
if is_dpraid_workspace_error "${show_output}"; then
    warn "dpraid show reported workspace write error; recreate jobs dir and retry once"
    ensure_dpraid_workspace
    set +e
    show_output="$(run_dpraid show 2>&1)"
    show_rc=$?
    set -e
    printf '%s\n' "${show_output}"
    if [ "${show_rc}" -ne 0 ] || is_dpraid_workspace_error "${show_output}"; then
        fail "dpraid show still cannot write under ${DPRAID_JOBS_DIR}"
        echo "[${NODE_IP}] hint: HOME=${HOME} DPRAID_HOME=${DPRAID_HOME}; ls -la ${DPRAID_HOME}" >&2
        ls -la "${DPRAID_HOME}" >&2 || true
        exit 1
    fi
fi
ok "dpraid show finished"

# Parse flash-clear targets from dpraid show:
#   1) Prefer ASICs table (header "Ctl ASIC ..." / "ASIC BDF ..."): use ASIC column.
#   2) Else legacy "CONTROLLER MODEL" table: use first-column ID.
# Skip ---/=== separators and strip ANSI. Do not treat DID lists as targets.
mapfile -t controller_ids < <(
    printf '%s\n' "${show_output}" | awk '
        {
            gsub(/\n/, "")
            gsub(/\033\[[0-9;]*[A-Za-z]/, "")
            $0 = $0
        }
        BEGIN { mode = "" }
        # New format ASICs table (ASIC id == former Ctrl /cX id).
        # Do not match Controllers header "Ctl Model ... ASICs Status".
        toupper($0) ~ /(^|[[:space:]])CTL[[:space:]]+ASIC([[:space:]]|$)/ ||
        toupper($0) ~ /ASIC[[:space:]]+BDF/ {
            mode = "asic"
            next
        }
        toupper($0) ~ /CONTROLLER[[:space:]]+MODEL/ {
            if (mode == "") mode = "legacy"
            next
        }
        mode == "" { next }
        NF == 0 { exit }
        $0 ~ /^[[:space:]\-_=]+$/ { next }
        mode == "asic" && $1 ~ /^[0-9]+$/ && $2 ~ /^[0-9]+$/ {
            print $2 + 0
            next
        }
        mode == "legacy" && $1 ~ /^[0-9]+$/ {
            print $1 + 0
            next
        }
        { exit }
    ' | sort -n -u
)

if [ "${#controller_ids[@]}" -eq 0 ]; then
    fail "no flash-clear targets parsed from dpraid show (need ASICs 'Ctl ASIC' rows or legacy 'CONTROLLER MODEL' ID rows)"
    echo "[${NODE_IP}] hint: new CLI ASICs table:" >&2
    echo "[${NODE_IP}]   Ctl ASIC BDF ... Status" >&2
    echo "[${NODE_IP}]   0   0    01:00.0 ... Optimal" >&2
    echo "[${NODE_IP}] hint: legacy controller table:" >&2
    echo "[${NODE_IP}]   ID CONTROLLER MODEL ... STAT ..." >&2
    echo "[${NODE_IP}]   0  DAPUSTOR ...        Optimal ..." >&2
    exit 1
fi

targets=()
for controller_id in "${controller_ids[@]}"; do
    targets+=("/c${controller_id}")
done
ok "found ${#controller_ids[@]} flash-clear target(s): ${targets[*]}"

banner "2/2 flash-clear --with-cache --force"
idx=0
for controller_id in "${controller_ids[@]}"; do
    idx=$((idx + 1))
    target="/c${controller_id}"
    echo "[${NODE_IP}] --- (${idx}/${#controller_ids[@]}) ${DPRAID_BIN} ${target} flash-clear --with-cache --force ---"
    set +e
    clear_output="$(run_dpraid "${target}" flash-clear --with-cache --force 2>&1)"
    clear_rc=$?
    set -e
    if [ -n "${clear_output}" ]; then
        printf '%s\n' "${clear_output}"
    fi
    if { [ "${clear_rc}" -ne 0 ] || is_dpraid_workspace_error "${clear_output}"; }; then
        if is_dpraid_workspace_error "${clear_output}"; then
            warn "${target} hit dpraid workspace write error; recreate jobs dir and retry once"
            ensure_dpraid_workspace
            set +e
            clear_output="$(run_dpraid "${target}" flash-clear --with-cache --force 2>&1)"
            clear_rc=$?
            set -e
            if [ -n "${clear_output}" ]; then
                printf '%s\n' "${clear_output}"
            fi
        fi
    fi
    if [ "${clear_rc}" -ne 0 ] || is_dpraid_workspace_error "${clear_output}"; then
        fail "${DPRAID_BIN} ${target} flash-clear --with-cache --force failed (rc=${clear_rc})"
        echo "[${NODE_IP}] hint: check controller ${target}, HOME=${HOME}, ${DPRAID_JOBS_DIR} writability" >&2
        show_disk "${DPRAID_HOME}" >&2 || true
        ls -la "${DPRAID_HOME}" >&2 || true
        exit 1
    fi
    ok "${target} flash-clear --with-cache --force succeeded"
done

banner "CSD flash+cache clear DONE"
ok "cleared controller(s): ${targets[*]}"
echo ""
