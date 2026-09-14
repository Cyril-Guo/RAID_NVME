#!/usr/bin/env bash
set -euo pipefail

: "${NODE_IP:?NODE_IP is required}"
: "${TARGET_USER:?TARGET_USER is required}"
: "${REMOTE_DIR:?REMOTE_DIR is required}"
: "${REMOTE_SSH_COMMAND:?REMOTE_SSH_COMMAND is required}"
: "${REMOTE_SCP_COMMAND:?REMOTE_SCP_COMMAND is required}"

report_suffix="${REPORT_SUFFIX:-}"
log_suffix="${LOG_SUFFIX:-}"
execution_log="test_execution_${NODE_IP}${log_suffix}.log"
report_file="node-report_${NODE_IP}${report_suffix}.xml"
remote_junit="${REMOTE_DIR}/reports/junit.xml"
remote_rc_file="${REMOTE_DIR}/cli_test.rc"

echo "[${NODE_IP}] install pytest if missing"
eval "${REMOTE_SSH_COMMAND} 'python3 -m pip install -q -r ${REMOTE_DIR}/requirements.txt || true'"

echo "[${NODE_IP}] run CLI tests (step-by-step, full command echo)"
set +e
eval "${REMOTE_SSH_COMMAND} 'bash -s'" <<REMOTE
set -o pipefail
cd '${REMOTE_DIR}'
mkdir -p reports
export CLI_JUNIT_XML='${remote_junit}'
export PYTHONUNBUFFERED=1
python3 -u nvme_raid_test.py 2>&1 | tee '${REMOTE_DIR}/${execution_log}'
echo \${PIPESTATUS[0]} > '${remote_rc_file}'
REMOTE
set -e

test_rc="$(eval "${REMOTE_SSH_COMMAND} \"cat '${remote_rc_file}' 2>/dev/null || echo 1\"" | tr -d '\r' | tail -n 1)"
test_rc="${test_rc:-1}"

echo "[${NODE_IP}] collect junit/log (rc=${test_rc})"
eval "${REMOTE_SCP_COMMAND} ${TARGET_USER}@${NODE_IP}:${remote_junit} ${report_file}" 2>/dev/null || {
    echo "[${NODE_IP}] WARN: junit missing, writing empty suite"
    cat > "${report_file}" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<testsuite name="cli" tests="0" failures="0" errors="0" skipped="0"/>
EOF
}
eval "${REMOTE_SCP_COMMAND} ${TARGET_USER}@${NODE_IP}:${REMOTE_DIR}/${execution_log} ${execution_log}" 2>/dev/null || true

exit "${test_rc}"
