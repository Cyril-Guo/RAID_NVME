#!/usr/bin/env bash
set -euo pipefail

: "${NODE_IP:?NODE_IP is required}"
: "${TARGET_USER:?TARGET_USER is required}"
: "${REMOTE_DIR:?REMOTE_DIR is required}"
: "${REMOTE_SSH_COMMAND:?REMOTE_SSH_COMMAND is required}"
: "${REMOTE_SCP_COMMAND:?REMOTE_SCP_COMMAND is required}"
: "${TEST_IDLE_TIMEOUT_MINUTES:?TEST_IDLE_TIMEOUT_MINUTES is required}"

qemu_target="${QEMU_VM_TARGET:-0}"
allow_fio="${ALLOW_DESTRUCTIVE_FIO:-1}"
report_suffix="${REPORT_SUFFIX:-}"
log_suffix="${LOG_SUFFIX:-}"
test_label="${TEST_LABEL:-nvme_raid_test.py}"
execution_log="test_execution_${NODE_IP}${log_suffix}.log"
debug_log="debug_${NODE_IP}${log_suffix}.log"
report_file="report_${NODE_IP}${report_suffix}.xml"
idle_timeout_seconds=$((TEST_IDLE_TIMEOUT_MINUTES * 60))
watch_interval_seconds=30
diagnostics_collected=0
target_kind=physical
[ "${qemu_target}" != "1" ] || target_kind=qemu
[ "${report_suffix}" != "_physical" ] || target_kind=physical
printf 'TEST_EXECUTION_TARGET=%s\n' "${target_kind}" > "${execution_log}"

bounded() {
    local label="$1" limit="$2" command="$3" rc=0
    timeout --kill-after=5s "${limit}s" bash -c "${command}" || rc=$?
    if [ "${rc}" != "0" ]; then
        printf '[COLLECTION_WARNING] %s rc=%s (timeout=124/137); missing artifacts remain visible in report.\n' "${label}" "${rc}" | tee -a "${execution_log}" "${debug_log}"
    fi
    return "${rc}"
}

record_failure() {
    {
        echo "[${NODE_IP}] ERROR: ${test_label} failed with exit code $1"
        echo "TEST_EXECUTION_STATUS=failed"
        echo "TEST_EXECUTION_EXIT_CODE=$1"
        echo "TEST_EXECUTION_FAILED_AT=$(date +%s)"
    } | tee -a "${execution_log}"
    python3 ci/execution_failure.py --describe "${execution_log}" | tee -a "${execution_log}" || true
}

collect_failure_diagnostics() {
    [ "${diagnostics_collected}" = "0" ] || return 0
    diagnostics_collected=1
    {
        echo "[DIAGNOSTICS] target=${NODE_IP} snapshot before cleanup; maximum SSH time=45s"
        python3 ci/execution_failure.py --describe "${execution_log}" || true
    } | tee -a "${debug_log}"
    local rc=0
    timeout --kill-after=5s 45s bash -c "${REMOTE_SSH_COMMAND} \"cd ${REMOTE_DIR} && sudo -n bash ci/collect_hang_diagnostics.sh\"" >> "${debug_log}" 2>&1 || rc=$?
    echo "[DIAGNOSTICS] snapshot rc=${rc}; target unavailable, permission errors or timeout are recorded in ${debug_log}" | tee -a "${execution_log}" "${debug_log}"
}

collect_io_signature() {
    local snapshot
    snapshot="$(timeout --kill-after=5s 20s bash -c "
        ${REMOTE_SSH_COMMAND} \"cd ${REMOTE_DIR} && bash ci/io_progress_signature.sh\"
    " 2>/dev/null)" || return 1
    [ -n "${snapshot}" ] || return 1
    printf '%s' "${snapshot}" | sha256sum | awk '{ print $1 }'
}

echo "[${NODE_IP}] run ${test_label}"
set +e
remote_test_command="${REMOTE_SSH_COMMAND} \"cd ${REMOTE_DIR} && QEMU_VM_TARGET=${qemu_target} ALLOW_DESTRUCTIVE_FIO=${allow_fio} TEST_IDLE_TIMEOUT_MINUTES=${TEST_IDLE_TIMEOUT_MINUTES} sudo -E python3 -u nvme_raid_test.py\""
setsid bash -c "set -o pipefail; ${remote_test_command} 2>&1 | awk '{ print strftime(\"[%Y-%m-%d %H:%M:%S]\"), \$0; fflush() }' | tee -a '${execution_log}'" &
test_pid=$!
# Cancellation is not a test failure; Jenkins retains ABORTED notification policy.
trap 'kill -TERM "-${test_pid}" 2>/dev/null || true; exit 143' TERM INT
last_progress_ts=$(date +%s)
last_log_size=0
last_io_signature="$(collect_io_signature || true)"
idle_timed_out=0

while kill -0 "${test_pid}" 2>/dev/null; do
    sleep "${watch_interval_seconds}"
    kill -0 "${test_pid}" 2>/dev/null || break
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
        record_failure 124
        collect_failure_diagnostics
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

if [ "${idle_timed_out}" = "1" ]; then
    echo "[${NODE_IP}] ERROR: ${test_label} idle watchdog fired after ${TEST_IDLE_TIMEOUT_MINUTES} minutes without progress, target may be hung." | tee -a "${execution_log}"
fi

# Record failure before collection: SSH/SCP can fail independently.
if [ "${test_rc}" != "0" ]; then
    record_failure "${test_rc}"
    collect_failure_diagnostics
fi

# Best-effort remote cleanup/report salvage after kill or normal exit.
# Keep the monitor pattern out of this SSH cmdline; salvage script uses a self-safe pkill pattern.
bounded salvage 180 "${REMOTE_SSH_COMMAND} \"cd ${REMOTE_DIR} && PYTHONPATH=${REMOTE_DIR} python3 ci/salvage_junit_reports.py --stop-monitor --output report.xml\"" || true

echo "[${NODE_IP}] copy back reports"
mkdir -p allure-results
tmp_results="$(mktemp -d "./allure-results-${NODE_IP}${report_suffix}.XXXXXX")"
bounded allure_scp 180 "${REMOTE_SCP_COMMAND} -r ${TARGET_USER}@${NODE_IP}:${REMOTE_DIR}/allure-results '${tmp_results}/results'" || true
if [ -d "${tmp_results}/results" ]; then
    python3 ci/mark_allure_target_context.py "${tmp_results}/results" "${NODE_IP}" "${report_suffix}" "${qemu_target}" || true
    cp -R "${tmp_results}/results/." ./allure-results/ || true
fi
bounded junit_scp 60 "${REMOTE_SCP_COMMAND} ${TARGET_USER}@${NODE_IP}:${REMOTE_DIR}/report.xml ./${report_file}" || true
if [ ! -f "${report_file}" ]; then
    # Fallback: pull only known per-item reports into an isolated temporary directory.
    item_dir="$(mktemp -d "./item-junit-${NODE_IP}${report_suffix}.XXXXXX")"
    item_list="$(python3 -c 'import nvme_raid_test; print(" ".join(nvme_raid_test.TEST_ITEMS))')"
    for item in ${item_list}; do
        bounded "junit_${item}" 10 "${REMOTE_SCP_COMMAND} ${TARGET_USER}@${NODE_IP}:${REMOTE_DIR}/report_${item}.xml '${item_dir}/'" || true
    done
    PYTHONPATH=. python3 ci/salvage_junit_reports.py --from-dir "${item_dir}" --output "$(pwd)/${report_file}" || true
fi

if [ "${test_rc}" != "0" ]; then
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
