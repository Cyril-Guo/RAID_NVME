#!/usr/bin/env bash
# Enable unlimited userspace cores and relax ptrace so root gcore can attach.
# Best-effort; never fails the caller.
set -uo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/.." && pwd)
REMOTE_DIR=${REMOTE_DIR:-${REPO_ROOT}}
CORE_DIR="${REMOTE_DIR}/failure_bundles/cores"
NODE_IP=${NODE_IP:-unknown}

mkdir -p "${CORE_DIR}" 2>/dev/null || true

# Soft+hard unlimited for this shell and children when sourced/executed under bash.
ulimit -c unlimited 2>/dev/null || true

pattern="${CORE_DIR}/core.%e.%p"
if [ -w /proc/sys/kernel/core_pattern ] 2>/dev/null; then
    echo "${pattern}" >/proc/sys/kernel/core_pattern 2>/dev/null \
        && echo "[${NODE_IP}] kernel.core_pattern=${pattern}" \
        || echo "[${NODE_IP}] WARN: cannot write kernel.core_pattern" >&2
elif command -v sysctl >/dev/null 2>&1; then
    sysctl -w "kernel.core_pattern=${pattern}" >/dev/null 2>&1 \
        && echo "[${NODE_IP}] kernel.core_pattern=${pattern}" \
        || echo "[${NODE_IP}] WARN: sysctl kernel.core_pattern failed" >&2
fi

# Yama ptrace_scope blocks gcore attach even for same-uid / root when set to 1+.
# 0 = classic ptrace permissions (required for reliable gcore on live fio/dpraid).
write_ptrace_scope() {
    local value="$1"
    if [ -w /proc/sys/kernel/yama/ptrace_scope ] 2>/dev/null; then
        echo "${value}" >/proc/sys/kernel/yama/ptrace_scope 2>/dev/null && return 0
    fi
    if command -v sysctl >/dev/null 2>&1; then
        sysctl -w "kernel.yama.ptrace_scope=${value}" >/dev/null 2>&1 && return 0
    fi
    return 1
}

if [ -r /proc/sys/kernel/yama/ptrace_scope ]; then
    old_scope=$(cat /proc/sys/kernel/yama/ptrace_scope 2>/dev/null || echo "?")
    if write_ptrace_scope 0; then
        new_scope=$(cat /proc/sys/kernel/yama/ptrace_scope 2>/dev/null || echo "?")
        echo "[${NODE_IP}] kernel.yama.ptrace_scope ${old_scope} -> ${new_scope}"
    else
        echo "[${NODE_IP}] WARN: cannot set kernel.yama.ptrace_scope (was ${old_scope})" >&2
    fi
fi

if ! command -v gcore >/dev/null 2>&1; then
    echo "[${NODE_IP}] WARN: gcore not found; install gdb for failure gcore dumps" >&2
fi

exit 0
