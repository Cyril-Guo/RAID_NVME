#!/usr/bin/env bash
set -euo pipefail

: "${NODE_IP:?NODE_IP is required}"
: "${TARGET_USER:?TARGET_USER is required}"
: "${REMOTE_DIR:?REMOTE_DIR is required}"
: "${REMOTE_SSH_COMMAND:?REMOTE_SSH_COMMAND is required}"
: "${REMOTE_SCP_COMMAND:?REMOTE_SCP_COMMAND is required}"
: "${TEST_IDLE_TIMEOUT_MINUTES:?TEST_IDLE_TIMEOUT_MINUTES is required}"

qemu_target="${QEMU_VM_TARGET:-0}"
allow_fio="${ALLOW_DESTRUCTIVE_FIO:-YES}"
report_suffix="${REPORT_SUFFIX:-}"
log_suffix="${LOG_SUFFIX:-}"
test_label="${TEST_LABEL:-nvme_raid_test.py}"
execution_log="test_execution_${NODE_IP}${log_suffix}.log"
report_file="report_${NODE_IP}${report_suffix}.xml"
tmp_results="allure-results-${NODE_IP}${report_suffix}"
idle_timeout_seconds=$((TEST_IDLE_TIMEOUT_MINUTES * 60))
watch_interval_seconds=30
watchdog_heartbeat_seconds="${TEST_WATCHDOG_HEARTBEAT_SECONDS:-60}"

collect_io_signature() {
    timeout --kill-after=5s 20s bash -c "
        ${REMOTE_SSH_COMMAND} \"cd ${REMOTE_DIR} && chmod +x ci/io_progress_signature.sh && ci/io_progress_signature.sh\"
    " 2>/dev/null | sha256sum | awk '{ print $1 }'
}

collect_hang_diagnostics() {
    local diag_script=".hang_diagnostics_${NODE_IP}${log_suffix}.sh"

    cat > "${diag_script}" <<'DIAG'
#!/usr/bin/env bash
set +e
echo "===== idle watchdog diagnostics begin ====="
date
uptime || true
echo "--- process snapshot ---"
ps -eo pid,ppid,stat,etime,comm,args | grep -E 'fio|pytest|nvme_raid_test|python3|fio-test' | grep -v grep || true
echo "--- fio-test service status ---"
systemctl status fio-test.service --no-pager -l || true
echo "--- fio-test journal tail ---"
journalctl -u fio-test.service --no-pager -n 200 || true
echo "--- iostat non-system disk snapshot ---"
if command -v iostat >/dev/null 2>&1; then
    iostat -dx 1 3 || true
else
    echo "iostat not found"
fi
echo "--- block devices ---"
lsblk -o NAME,SIZE,TYPE,MOUNTPOINTS || true
echo "--- dmesg tail ---"
dmesg | tail -n 200 || true
echo "===== idle watchdog diagnostics end ====="
DIAG

    {
        echo "[${NODE_IP}] collect idle watchdog diagnostics before killing ${test_label}"
        timeout --kill-after=5s 30s bash -c "${REMOTE_SCP_COMMAND} '${diag_script}' ${TARGET_USER}@${NODE_IP}:${REMOTE_DIR}/${diag_script}" || echo "[${NODE_IP}] WARN: failed to upload watchdog diagnostics script"
        timeout --kill-after=5s 90s bash -c "${REMOTE_SSH_COMMAND} 'cd ${REMOTE_DIR} && chmod +x ${diag_script} && ./${diag_script}'" || echo "[${NODE_IP}] WARN: failed to collect watchdog diagnostics"
    } 2>&1 | tee -a "${execution_log}"

    rm -f "${diag_script}"
    last_log_size=$(wc -c < "${execution_log}" 2>/dev/null || echo 0)
}

echo "[${NODE_IP}] run ${test_label}"
set +e
remote_test_command="${REMOTE_SSH_COMMAND} \"cd ${REMOTE_DIR} && QEMU_VM_TARGET=${qemu_target} ALLOW_DESTRUCTIVE_FIO=${allow_fio} TEST_IDLE_TIMEOUT_MINUTES=${TEST_IDLE_TIMEOUT_MINUTES} sudo -E python3 nvme_raid_test.py\""
setsid bash -c "set -o pipefail; ${remote_test_command} 2>&1 | awk '{ print strftime(\"[%Y-%m-%d %H:%M:%S]\"), \$0; fflush() }' | tee '${execution_log}'" &
test_pid=$!
last_progress_ts=$(date +%s)
last_log_size=0
last_io_signature="$(collect_io_signature || true)"
idle_timed_out=0
last_watchdog_log_ts=0

while kill -0 "${test_pid}" 2>/dev/null; do
    sleep "${watch_interval_seconds}"
    now_ts=$(date +%s)
    current_log_size=$(wc -c < "${execution_log}" 2>/dev/null || echo 0)
    current_io_signature="$(collect_io_signature || true)"
    log_progress=0
    io_progress=0

    if [ "${current_log_size}" != "${last_log_size}" ]; then
        last_progress_ts="${now_ts}"
        last_log_size="${current_log_size}"
        log_progress=1
    fi

    if [ -n "${current_io_signature}" ] && [ "${current_io_signature}" != "${last_io_signature}" ]; then
        last_progress_ts="${now_ts}"
        last_io_signature="${current_io_signature}"
        io_progress=1
    fi

    idle_seconds=$((now_ts - last_progress_ts))
    if [ $((now_ts - last_watchdog_log_ts)) -ge "${watchdog_heartbeat_seconds}" ]; then
        echo "[${NODE_IP}] watchdog: ${test_label} running, idle=${idle_seconds}s, log_bytes=${current_log_size}, log_progress=${log_progress}, io_progress=${io_progress}" | tee -a "${execution_log}"
        last_watchdog_log_ts="${now_ts}"
        last_log_size=$(wc -c < "${execution_log}" 2>/dev/null || echo 0)
    fi

    if [ "${idle_seconds}" -ge "${idle_timeout_seconds}" ]; then
        idle_timed_out=1
        echo "[${NODE_IP}] ERROR: ${test_label} made no log or non-system disk IO progress for ${TEST_IDLE_TIMEOUT_MINUTES} minutes, treat as hung." | tee -a "${execution_log}"
        collect_hang_diagnostics
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

echo "[${NODE_IP}] copy back reports"
mkdir -p allure-results
rm -rf "${tmp_results}"
eval "${REMOTE_SCP_COMMAND} -r ${TARGET_USER}@${NODE_IP}:${REMOTE_DIR}/allure-results ./${tmp_results}" || true
if [ -d "${tmp_results}" ]; then
    python3 ci/mark_allure_target_context.py "${tmp_results}" "${NODE_IP}" "${report_suffix}" "${qemu_target}" || true
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
