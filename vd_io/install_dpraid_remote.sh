#!/bin/bash
set -euo pipefail

: "${NODE_IP:?NODE_IP is required}"
: "${TARGET_USER:?TARGET_USER is required}"
: "${DPRAID_SOURCE:?DPRAID_SOURCE is required}"
: "${BUILD_NUMBER:?BUILD_NUMBER is required}"

SSH_OPTS=${SSH_OPTS:-}
TARGET_PASSWORD=${TARGET_PASSWORD:-123456}
export SSHPASS="${TARGET_PASSWORD}"
REMOTE_SSH_COMMAND=${REMOTE_SSH_COMMAND:-}
REMOTE_SCP_COMMAND=${REMOTE_SCP_COMMAND:-}
TMP_SUFFIX=${TMP_SUFFIX:-}

if [ -z "${REMOTE_SSH_COMMAND}" ]; then
    REMOTE_SSH_COMMAND="sshpass -e ssh ${SSH_OPTS} ${TARGET_USER}@${NODE_IP}"
fi
if [ -z "${REMOTE_SCP_COMMAND}" ]; then
    REMOTE_SCP_COMMAND="sshpass -e scp ${SSH_OPTS}"
fi

remote_tmp="/tmp/dpraid_${BUILD_NUMBER}${TMP_SUFFIX}"
eval "${REMOTE_SCP_COMMAND} '${DPRAID_SOURCE}' '${TARGET_USER}@${NODE_IP}:${remote_tmp}'"
# Install to /usr/bin; when REMOTE_DIR is set, also stage a copy for per-case refresh.
# Install/help failures must fail this step (no trailing always-true clause).
if [ -n "${REMOTE_DIR:-}" ]; then
    eval "${REMOTE_SSH_COMMAND}" \
        "install -m 0755 '${remote_tmp}' /usr/bin/dpraid && mkdir -p '${REMOTE_DIR}/artifacts' && install -m 0755 '${remote_tmp}' '${REMOTE_DIR}/artifacts/dpraid' && rm -f '${remote_tmp}' && /usr/bin/dpraid --help >/dev/null"
else
    eval "${REMOTE_SSH_COMMAND}" \
        "install -m 0755 '${remote_tmp}' /usr/bin/dpraid && rm -f '${remote_tmp}' && /usr/bin/dpraid --help >/dev/null"
fi

