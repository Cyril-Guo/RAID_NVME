#!/usr/bin/env bash
# Enable unlimited userspace cores and point core_pattern at workspace cores/.
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

if ! command -v gcore >/dev/null 2>&1; then
    echo "[${NODE_IP}] WARN: gcore not found; install gdb for failure gcore dumps" >&2
fi

exit 0
