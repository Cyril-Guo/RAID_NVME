#!/usr/bin/env bash
set -euo pipefail

: "${NODE_IP:?NODE_IP is required}"
: "${TARGET_USER:?TARGET_USER is required}"
: "${REMOTE_DIR:?REMOTE_DIR is required}"
: "${REMOTE_SSH_COMMAND:?REMOTE_SSH_COMMAND is required}"
: "${REMOTE_SCP_COMMAND:?REMOTE_SCP_COMMAND is required}"
: "${TEST_IDLE_TIMEOUT_MINUTES:?TEST_IDLE_TIMEOUT_MINUTES is required}"

report_suffix="${REPORT_SUFFIX:-}"
log_suffix="${LOG_SUFFIX:-}"
test_label="${TEST_LABEL:-nvme_raid_test.py}"
execution_log="test_execution_${NODE_IP}${log_suffix}.log"
report_file="report_${NODE_IP}${report_suffix}.xml"
tmp_results="allure-results-${NODE_IP}${report_suffix}"
idle_timeout_seconds=$((TEST_IDLE_TIMEOUT_MINUTES * 60))
watch_interval_seconds=30

collect_io_signature() {
    timeout --kill-after=5s 20s bash -c "
        ${REMOTE_SSH_COMMAND} \"cd ${REMOTE_DIR} && chmod +x ci/io_progress_signature.sh && ci/io_progress_signature.sh\"
    " 2>/dev/null | sha256sum | awk '{ print $1 }'
}

echo "[${NODE_IP}] run ${test_label}"
set +e
remote_test_command="${REMOTE_SSH_COMMAND} \"cd ${REMOTE_DIR} && TEST_IDLE_TIMEOUT_MINUTES=${TEST_IDLE_TIMEOUT_MINUTES} sudo -E python3 nvme_raid_test.py\""
setsid bash -c "set -o pipefail; ${remote_test_command} 2>&1 | awk '{ print strftime(\"[%Y-%m-%d %H:%M:%S]\"), \$0; fflush() }' | tee '${execution_log}'" &
test_pid=$!
last_progress_ts=$(date +%s)
last_log_size=0
last_io_signature="$(collect_io_signature || true)"
idle_timed_out=0

while kill -0 "${test_pid}" 2>/dev/null; do
    sleep "${watch_interval_seconds}"
    now_ts=$(date +%s)
    current_log_size=$(wc -c < "${execution_log}" 2>/dev/null || echo 0)
    current_io_signature="$(collect_io_signature || true)"

    if [ "${current_log_size}" != "${last_log_size}" ]; then
        last_progress_ts="${now_ts}"
        last_log_size="${current_log_size}"
    fi

    if [ -n "${current_io_signature}" ] && [ "${current_io_signature}" != "${last_io_signature}" ]; then
        last_progress_ts="${now_ts}"
        last_io_signature="${current_io_signature}"
    fi

    if [ $((now_ts - last_progress_ts)) -ge "${idle_timeout_seconds}" ]; then
        idle_timed_out=1
        echo "[${NODE_IP}] ERROR: ${test_label} made no log or non-system disk IO progress for ${TEST_IDLE_TIMEOUT_MINUTES} minutes, treat as hung." | tee -a "${execution_log}"
        kill -TERM "-${test_pid}" 2>/dev/null || kill -TERM "${test_pid}" 2>/dev/null || true
        sleep 5
        kill -KILL "-${test_pid}" 2>/dev/null || kill -KILL "${test_pid}" 2>/dev/null || true
        break
    fi
done

if [ "${idle_timed_out}" = "1" ]; then
    wait "${test_pid}" 2>/dev/null || true
    test_rc=124
else
    wait "${test_pid}"
    test_rc=$?
fi
set -e

if [ "${test_rc}" = "124" ] || [ "${test_rc}" = "137" ]; then
    echo "[${NODE_IP}] ERROR: ${test_label} idle watchdog fired after ${TEST_IDLE_TIMEOUT_MINUTES} minutes without progress, target may be hung." | tee -a "${execution_log}"
fi

# Best-effort remote cleanup/report salvage after kill or normal exit.
# Keep the monitor pattern out of this SSH cmdline; salvage script uses a self-safe pkill pattern.
eval "${REMOTE_SSH_COMMAND} \"cd ${REMOTE_DIR} && python3 ci/salvage_junit_reports.py --stop-monitor --output report.xml\"" || true

if [ "${test_rc}" != "0" ]; then
    echo "[${NODE_IP}] collect failure gcore/diagnostic bundle on DUT"
    eval "${REMOTE_SSH_COMMAND} \"cd ${REMOTE_DIR} && chmod +x ci/collect_failure_bundle.sh ci/enable_failure_coredumps.sh && NODE_IP=${NODE_IP} REMOTE_DIR=${REMOTE_DIR} RUN_KEY=remote_runner BUNDLE_REASON=remote_test_rc_${test_rc} ci/enable_failure_coredumps.sh && NODE_IP=${NODE_IP} REMOTE_DIR=${REMOTE_DIR} RUN_KEY=remote_runner BUNDLE_REASON=remote_test_rc_${test_rc} ci/collect_failure_bundle.sh\"" || true
    mkdir -p .
    eval "${REMOTE_SCP_COMMAND} ${TARGET_USER}@${NODE_IP}:${REMOTE_DIR}/failure_bundles/failure_bundle_*.tar.gz ." || true
fi

echo "[${NODE_IP}] copy back reports"
mkdir -p allure-results
rm -rf "${tmp_results}"
eval "${REMOTE_SCP_COMMAND} -r ${TARGET_USER}@${NODE_IP}:${REMOTE_DIR}/allure-results ./${tmp_results}" || true
if [ -d "${tmp_results}" ]; then
    python3 ci/mark_allure_target_context.py "${tmp_results}" "${NODE_IP}" || true
    cp -R "${tmp_results}/." ./allure-results/ || true
    rm -rf "${tmp_results}"
fi
eval "${REMOTE_SCP_COMMAND} ${TARGET_USER}@${NODE_IP}:${REMOTE_DIR}/report.xml ./${report_file}" || true
if [ ! -f "${report_file}" ]; then
    # Fallback: pull known per-item reports into a temp dir, merge, then delete temp files.
    item_dir="item-junit-${NODE_IP}${report_suffix}"
    rm -rf "${item_dir}"
    mkdir -p "${item_dir}"
    eval "${REMOTE_SCP_COMMAND} ${TARGET_USER}@${NODE_IP}:${REMOTE_DIR}/report_*.xml ${item_dir}/" 2>/dev/null || true
    python3 ci/salvage_junit_reports.py --from-dir "${item_dir}" --output "${report_file}" || true
    rm -rf "${item_dir}"
fi

if [ "${test_rc}" != "0" ]; then
    {
        echo "[${NODE_IP}] ERROR: ${test_label} failed with exit code ${test_rc}"
        echo "TEST_EXECUTION_STATUS=failed"
        echo "TEST_EXECUTION_EXIT_CODE=${test_rc}"
    } | tee -a "${execution_log}"
    exit "${test_rc}"
fi

if [ ! -f "${report_file}" ]; then
    {
        echo "[${NODE_IP}] ERROR: Missing ${report_file}. ${test_label} did not produce a JUnit report."
        echo "TEST_EXECUTION_STATUS=failed"
        echo "TEST_EXECUTION_EXIT_CODE=2"
    } | tee -a "${execution_log}"
    exit 2
fi

echo "TEST_EXECUTION_STATUS=passed" >> "${execution_log}"
