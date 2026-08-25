#!/usr/bin/env bash
# Enable userspace coredumps on the DUT for CI triage:
#   - unlimited core size (limits.d, survives new SSH sessions)
#   - core_pattern -> workspace failure_bundles/cores/
#   - yama.ptrace_scope=0 so root gcore can attach
# Best-effort; never fails the caller.
set -uo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/.." && pwd)
REMOTE_DIR=${REMOTE_DIR:-${REPO_ROOT}}
CORE_DIR="${REMOTE_DIR}/failure_bundles/cores"
NODE_IP=${NODE_IP:-unknown}
LIMITS_FILE=/etc/security/limits.d/99-raid-nvme-coredump.conf
SYSCTL_FILE=/etc/sysctl.d/99-raid-nvme-coredump.conf

mkdir -p "${CORE_DIR}" 2>/dev/null || true

# Soft+hard unlimited for this shell and children.
ulimit -c unlimited 2>/dev/null || true

# Persist unlimited cores for future login/SSH/sudo sessions (pam_limits).
if [ -d /etc/security/limits.d ] && [ -w /etc/security/limits.d ]; then
    cat >"${LIMITS_FILE}" <<'EOF'
# Managed by RAID_NVME ci/enable_failure_coredumps.sh — unlimited userspace cores.
*       soft    core    unlimited
*       hard    core    unlimited
root    soft    core    unlimited
root    hard    core    unlimited
EOF
    echo "[${NODE_IP}] wrote ${LIMITS_FILE}"
elif [ -w /etc/security/limits.conf ] 2>/dev/null; then
    if ! grep -q 'RAID_NVME ci/enable_failure_coredumps' /etc/security/limits.conf 2>/dev/null; then
        cat >>/etc/security/limits.conf <<'EOF'

# Managed by RAID_NVME ci/enable_failure_coredumps.sh
*       soft    core    unlimited
*       hard    core    unlimited
root    soft    core    unlimited
root    hard    core    unlimited
EOF
        echo "[${NODE_IP}] appended core unlimited to /etc/security/limits.conf"
    fi
else
    echo "[${NODE_IP}] WARN: cannot persist ulimit -c unlimited via limits.d" >&2
fi

# Ubuntu apport may hijack crashes; prefer plain files under workspace.
if [ -f /etc/default/apport ]; then
    sed -i 's/^enabled=.*/enabled=0/' /etc/default/apport 2>/dev/null || true
fi
if command -v systemctl >/dev/null 2>&1; then
    systemctl stop apport.service 2>/dev/null || true
    systemctl disable apport.service 2>/dev/null || true
fi

pattern="${CORE_DIR}/core.%e.%p"
write_sysctl_live() {
    local key="$1"
    local value="$2"
    local path="/proc/sys/${key//./\/}"
    if [ -w "${path}" ]; then
        echo "${value}" >"${path}" 2>/dev/null && return 0
    fi
    if command -v sysctl >/dev/null 2>&1; then
        sysctl -w "${key}=${value}" >/dev/null 2>&1 && return 0
    fi
    return 1
}

# Persist + apply kernel.core_pattern and ptrace_scope.
if [ -d /etc/sysctl.d ] && [ -w /etc/sysctl.d ]; then
    cat >"${SYSCTL_FILE}" <<EOF
# Managed by RAID_NVME ci/enable_failure_coredumps.sh
kernel.core_pattern=${pattern}
kernel.yama.ptrace_scope=0
fs.suid_dumpable=1
EOF
    echo "[${NODE_IP}] wrote ${SYSCTL_FILE}"
    if command -v sysctl >/dev/null 2>&1; then
        sysctl --system >/dev/null 2>&1 \
            || sysctl -p "${SYSCTL_FILE}" >/dev/null 2>&1 \
            || true
    fi
fi

if write_sysctl_live kernel.core_pattern "${pattern}"; then
    echo "[${NODE_IP}] kernel.core_pattern=${pattern}"
else
    echo "[${NODE_IP}] WARN: cannot set kernel.core_pattern" >&2
fi

# Yama ptrace_scope blocks gcore attach even for root when set to 1+.
if [ -r /proc/sys/kernel/yama/ptrace_scope ]; then
    old_scope=$(cat /proc/sys/kernel/yama/ptrace_scope 2>/dev/null || echo "?")
    if write_sysctl_live kernel.yama.ptrace_scope 0; then
        new_scope=$(cat /proc/sys/kernel/yama/ptrace_scope 2>/dev/null || echo "?")
        echo "[${NODE_IP}] kernel.yama.ptrace_scope ${old_scope} -> ${new_scope}"
    else
        echo "[${NODE_IP}] WARN: cannot set kernel.yama.ptrace_scope (was ${old_scope})" >&2
    fi
fi

if write_sysctl_live fs.suid_dumpable 1; then
    echo "[${NODE_IP}] fs.suid_dumpable=1"
fi

# Drop a profile snippet so interactive/non-pam shells also raise soft limit.
PROFILE_FILE=/etc/profile.d/99-raid-nvme-coredump.sh
if [ -d /etc/profile.d ] && [ -w /etc/profile.d ]; then
    cat >"${PROFILE_FILE}" <<'EOF'
# Managed by RAID_NVME ci/enable_failure_coredumps.sh
ulimit -c unlimited 2>/dev/null || true
EOF
    echo "[${NODE_IP}] wrote ${PROFILE_FILE}"
fi

if ! command -v gcore >/dev/null 2>&1; then
    echo "[${NODE_IP}] WARN: gcore not found; install gdb for failure gcore dumps" >&2
fi

echo "[${NODE_IP}] coredump enable done (ulimit/core_pattern/ptrace); cores -> ${CORE_DIR}"
exit 0
