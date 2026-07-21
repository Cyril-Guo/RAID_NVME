#!/usr/bin/env bash
set -euo pipefail

: "${NODE_IP:?NODE_IP is required}"
: "${TARGET_USER:?TARGET_USER is required}"
: "${REMOTE_DIR:?REMOTE_DIR is required}"
: "${REMOTE_SSH_COMMAND:?REMOTE_SSH_COMMAND is required}"
: "${REMOTE_SCP_COMMAND:?REMOTE_SCP_COMMAND is required}"
: "${TARGET_NODE_TIMEOUT_MINUTES:?TARGET_NODE_TIMEOUT_MINUTES is required}"

qemu_target="${QEMU_VM_TARGET:-0}"
allow_fio="${ALLOW_DESTRUCTIVE_FIO:-YES}"
report_suffix="${REPORT_SUFFIX:-}"
log_suffix="${LOG_SUFFIX:-}"
test_label="${TEST_LABEL:-nvme_raid_test.py}"
execution_log="test_execution_${NODE_IP}${log_suffix}.log"
report_file="report_${NODE_IP}${report_suffix}.xml"
tmp_results="allure-results-${NODE_IP}${report_suffix}"

echo "[${NODE_IP}] run ${test_label}"
set +e
timeout --kill-after=60s "${TARGET_NODE_TIMEOUT_MINUTES}m" bash -c "
    ${REMOTE_SSH_COMMAND} \"cd ${REMOTE_DIR} && QEMU_VM_TARGET=${qemu_target} ALLOW_DESTRUCTIVE_FIO=${allow_fio} sudo -E python3 nvme_raid_test.py\"
" 2>&1 | awk '{ print strftime("[%Y-%m-%d %H:%M:%S]"), $0 }' | tee "${execution_log}"
test_rc=${PIPESTATUS[0]}
set -e

if [ "${test_rc}" = "124" ] || [ "${test_rc}" = "137" ]; then
    echo "[${NODE_IP}] ERROR: ${test_label} timed out after ${TARGET_NODE_TIMEOUT_MINUTES} minutes, target may be hung." | tee -a "${execution_log}"
fi

echo "[${NODE_IP}] copy back reports"
mkdir -p allure-results
rm -rf "${tmp_results}"
eval "${REMOTE_SCP_COMMAND} -r ${TARGET_USER}@${NODE_IP}:${REMOTE_DIR}/allure-results ./${tmp_results}" || true
if [ -d "${tmp_results}" ]; then
    cp -R "${tmp_results}/." ./allure-results/ || true
    rm -rf "${tmp_results}"
fi
eval "${REMOTE_SCP_COMMAND} ${TARGET_USER}@${NODE_IP}:${REMOTE_DIR}/report.xml ./${report_file}" || true

if [ "${test_rc}" != "0" ]; then
    echo "[${NODE_IP}] ERROR: ${test_label} failed with exit code ${test_rc}"
    exit "${test_rc}"
fi

if [ ! -f "${report_file}" ]; then
    echo "[${NODE_IP}] ERROR: Missing ${report_file}. ${test_label} did not produce a JUnit report."
    exit 2
fi
