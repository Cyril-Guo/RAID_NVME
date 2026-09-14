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
failure_bundle_query_timeout_seconds="${FAILURE_BUNDLE_QUERY_TIMEOUT_SECONDS:-30}"
failure_bundle_collect_timeout_seconds="${FAILURE_BUNDLE_COLLECT_TIMEOUT_SECONDS:-600}"
failure_bundle_copy_timeout_seconds="${FAILURE_BUNDLE_COPY_TIMEOUT_SECONDS:-600}"
failure_bundle_kill_after_seconds="${FAILURE_BUNDLE_KILL_AFTER_SECONDS:-30}"
cleanup_timeout_seconds="${CLEANUP_TIMEOUT_SECONDS:-900}"
report_command_timeout_seconds="${REPORT_COMMAND_TIMEOUT_SECONDS:-120}"
report_copy_timeout_seconds="${REPORT_COPY_TIMEOUT_SECONDS:-300}"
cleanup_deadline=0

run_cleanup_command() {
    local label="$1"
    local requested_seconds="$2"
    local now remaining timeout_seconds
    shift 2
    now=$(date +%s)
    timeout_seconds="${requested_seconds}"
    if [[ "${cleanup_deadline}" -gt 0 ]]; then
        remaining=$((cleanup_deadline - now))
        if [[ "${remaining}" -le 0 ]]; then
            echo "[${NODE_IP}] WARN: cleanup budget exhausted before ${label}" >&2
            return 124
        fi
        if [[ "${remaining}" -lt "${timeout_seconds}" ]]; then
            timeout_seconds="${remaining}"
        fi
    fi
    echo "[${NODE_IP}] cleanup ${label} (timeout=${timeout_seconds}s)" >&2
    timeout --kill-after="${failure_bundle_kill_after_seconds}s" \
        "${timeout_seconds}s" "$@"
}

read_remote_bundle_pointer() {
    local pointer_name="$1"
    local pointer_command

    pointer_command="${REMOTE_SSH_COMMAND} \"cat '${REMOTE_DIR}/failure_bundles/${pointer_name}' 2>/dev/null || true\""
    run_cleanup_command "read failure bundle pointer" \
        "${failure_bundle_query_timeout_seconds}" bash -c "${pointer_command}" \
        2>/dev/null | tr -d '\r' | tail -n 1
}

is_expected_failure_bundle_path() {
    local bundle_path="${1:-}"
    local bundle_name

    case "${bundle_path}" in
        "${REMOTE_DIR}"/failure_bundles/*)
            ;;
        *)
            return 1
            ;;
    esac

    bundle_name="$(basename -- "${bundle_path}")"
    [[ "${bundle_name}" =~ ^failure_bundle_[A-Za-z0-9._-]+\.tar\.gz$ ]]
}

remote_bundle_exists() {
    local bundle_path="$1"
    local exists_command

    exists_command="${REMOTE_SSH_COMMAND} \"test -f '${bundle_path}'\""
    run_cleanup_command "verify failure bundle" \
        "${failure_bundle_query_timeout_seconds}" bash -c "${exists_command}" \
        >/dev/null 2>&1
}

find_remote_failure_bundle() {
    local pointer_name="$1"
    local bundle_path

    bundle_path="$(read_remote_bundle_pointer "${pointer_name}" || true)"
    if is_expected_failure_bundle_path "${bundle_path}" && remote_bundle_exists "${bundle_path}"; then
        printf '%s\n' "${bundle_path}"
        return 0
    fi
    return 1
}

collect_fallback_failure_bundle() {
    local collect_command
    local transport_timeout_seconds

    transport_timeout_seconds=$((failure_bundle_collect_timeout_seconds + failure_bundle_kill_after_seconds + 30))
    collect_command="${REMOTE_SSH_COMMAND} \"cd ${REMOTE_DIR} && chmod +x powercycle/collect_failure_bundle.sh powercycle/enable_failure_coredumps.sh && timeout --kill-after=${failure_bundle_kill_after_seconds}s ${failure_bundle_collect_timeout_seconds}s env NODE_IP=${NODE_IP} REMOTE_DIR=${REMOTE_DIR} RUN_KEY=remote_runner BUNDLE_REASON=remote_test_rc_${test_rc} bash -c 'powercycle/enable_failure_coredumps.sh && powercycle/collect_failure_bundle.sh'\""

    run_cleanup_command "fallback failure bundle" \
        "${transport_timeout_seconds}" bash -c "${collect_command}"
}

copy_exact_failure_bundle() {
    local remote_bundle_path="$1"
    local bundle_name
    local copy_command

    bundle_name="$(basename -- "${remote_bundle_path}")"
    echo "[${NODE_IP}] copy exact failure bundle ${bundle_name} (timeout=${failure_bundle_copy_timeout_seconds}s)"
    copy_command="${REMOTE_SCP_COMMAND} '${TARGET_USER}@${NODE_IP}:${remote_bundle_path}' ."
    run_cleanup_command "copy failure bundle" \
        "${failure_bundle_copy_timeout_seconds}" bash -c "${copy_command}"
}

collect_io_signature() {
    timeout --kill-after=5s 20s bash -c "
        ${REMOTE_SSH_COMMAND} \"cd ${REMOTE_DIR} && chmod +x powercycle/io_progress_signature.sh && powercycle/io_progress_signature.sh\"
    " 2>/dev/null | sha256sum | awk '{ print $1 }'
}

echo "[${NODE_IP}] run ${test_label}"
set +e
remote_test_command="${REMOTE_SSH_COMMAND} \"cd ${REMOTE_DIR} && NODE_IP=${NODE_IP} REMOTE_DIR=${REMOTE_DIR} TEST_IDLE_TIMEOUT_MINUTES=${TEST_IDLE_TIMEOUT_MINUTES} sudo -E bash -c 'ulimit -c unlimited; cd ${REMOTE_DIR} && NODE_IP=${NODE_IP} REMOTE_DIR=${REMOTE_DIR} TEST_IDLE_TIMEOUT_MINUTES=${TEST_IDLE_TIMEOUT_MINUTES} python3 nvme_raid_test.py'\""

# Console-first: print every line to Jenkins stdout; also append local artifact copy.
: >"${execution_log}"
console_print() {
    printf '%s\n' "$1"
    printf '%s\n' "$1" >>"${execution_log}"
}

dut_stream_dir="$(mktemp -d "/tmp/pc_dut_stream_${NODE_IP}_XXXXXX")"
stream_dut_runtime_logs_once() {
    local case_root remote_file key offset_file offset chunk
    case_root="$(
        timeout --kill-after=3s 15s bash -c "
            ${REMOTE_SSH_COMMAND} \"ls -1d ${REMOTE_DIR}/cases/*/IO_Stress/log/ResultLog 2>/dev/null | sort | tail -n 1\"
        " 2>/dev/null | tr -d '\r' | tail -n 1 || true
    )"
    [[ -n "${case_root}" ]] || return 0
    for key in reboot_command.log dc_command.log fio_result/result.log powercycle_resume.log reboot.log; do
        remote_file="${case_root}/${key}"
        offset_file="${dut_stream_dir}/$(printf '%s' "${key}" | tr '/.' '__')"
        offset="$(cat "${offset_file}" 2>/dev/null || echo 0)"
        chunk="$(
            timeout --kill-after=3s 20s bash -c "
                ${REMOTE_SSH_COMMAND} \"if [[ -f $(printf '%q' "${remote_file}") ]]; then dd if=$(printf '%q' "${remote_file}") bs=1 skip=${offset} status=none 2>/dev/null; fi\"
            " 2>/dev/null || true
        )"
        if [[ -n "${chunk}" ]]; then
            while IFS= read -r line || [[ -n "${line}" ]]; do
                console_print "[${NODE_IP}][DUT:${key}] ${line}"
            done <<<"${chunk}"
            offset=$((offset + ${#chunk}))
            printf '%s' "${offset}" >"${offset_file}"
        fi
    done
}

idle_timed_out=0
last_progress_ts=$(date +%s)
last_io_signature="$(collect_io_signature || true)"
last_log_size=0

(
    while true; do
        sleep "${watch_interval_seconds}"
        now_ts=$(date +%s)
        stream_dut_runtime_logs_once || true
        current_log_size=$(wc -c < "${execution_log}" 2>/dev/null || echo 0)
        current_io_signature="$(collect_io_signature || true)"
        progressed=0
        if [ "${current_log_size}" != "${last_log_size}" ]; then
            progressed=1
            last_log_size="${current_log_size}"
        fi
        if [ -n "${current_io_signature}" ] && [ "${current_io_signature}" != "${last_io_signature}" ]; then
            progressed=1
            last_io_signature="${current_io_signature}"
        fi
        if [ "${progressed}" = "1" ]; then
            last_progress_ts="${now_ts}"
            continue
        fi
        if [ $((now_ts - last_progress_ts)) -ge "${idle_timeout_seconds}" ]; then
            console_print "[${NODE_IP}] ERROR: ${test_label} made no log or non-system disk IO progress for ${TEST_IDLE_TIMEOUT_MINUTES} minutes, treat as hung."
            if [[ -f "${dut_stream_dir}/test_pgid" ]]; then
                pgid="$(cat "${dut_stream_dir}/test_pgid")"
                kill -TERM "-${pgid}" 2>/dev/null || true
                sleep 5
                kill -KILL "-${pgid}" 2>/dev/null || true
            fi
            printf '1' >"${dut_stream_dir}/idle_timed_out"
            exit 0
        fi
    done
) &
watchdog_pid=$!

: >"${dut_stream_dir}/raw.out"
setsid bash -c "set -o pipefail; ${remote_test_command} 2>&1" >"${dut_stream_dir}/raw.out" 2>&1 &
test_pid=$!
printf '%s' "${test_pid}" >"${dut_stream_dir}/test_pgid"

(
    for _ in $(seq 1 100); do
        [[ -f "${dut_stream_dir}/raw.out" ]] && break
        sleep 0.05
    done
    stdbuf -oL -eL tail -n +1 -F "${dut_stream_dir}/raw.out" 2>/dev/null | while IFS= read -r line; do
        console_print "[$(date '+%Y-%m-%d %H:%M:%S')] ${line}"
    done
) &
tail_pid=$!

wait "${test_pid}"
test_rc=$?
kill "${tail_pid}" 2>/dev/null || true
kill "${watchdog_pid}" 2>/dev/null || true
wait "${tail_pid}" 2>/dev/null || true
wait "${watchdog_pid}" 2>/dev/null || true
stream_dut_runtime_logs_once || true

if [[ -f "${dut_stream_dir}/idle_timed_out" ]]; then
    idle_timed_out=1
    test_rc=124
fi
rm -rf "${dut_stream_dir}" 2>/dev/null || true
set -e

cleanup_deadline=$(( $(date +%s) + cleanup_timeout_seconds ))

if [ "${test_rc}" != "0" ]; then
    echo "[${NODE_IP}] ERROR: ${test_label} failed with exit code ${test_rc}"

    echo "TEST_EXECUTION_STATUS=failed"

    echo "TEST_EXECUTION_EXIT_CODE=${test_rc}"

    {
        echo "[${NODE_IP}] ERROR: ${test_label} failed with exit code ${test_rc}"
        echo "TEST_EXECUTION_STATUS=failed"
        echo "TEST_EXECUTION_EXIT_CODE=${test_rc}"
    } >>"${execution_log}"

fi

if [ "${test_rc}" = "124" ] || [ "${test_rc}" = "137" ]; then
    echo "[${NODE_IP}] ERROR: ${test_label} idle watchdog fired after ${TEST_IDLE_TIMEOUT_MINUTES} minutes without progress, target may be hung."
    echo "[${NODE_IP}] ERROR: ${test_label} idle watchdog fired after ${TEST_IDLE_TIMEOUT_MINUTES} minutes without progress, target may be hung." >>"${execution_log}"
fi

# Best-effort remote cleanup/report salvage after kill or normal exit.
# Keep the monitor pattern out of this SSH cmdline; salvage script uses a self-safe pkill pattern.
salvage_command="${REMOTE_SSH_COMMAND} \"cd ${REMOTE_DIR} && python3 powercycle/salvage_junit_reports.py --stop-monitor --output report.xml\""
run_cleanup_command "salvage remote reports" "${report_command_timeout_seconds}" \
    bash -c "${salvage_command}" || true

if [ "${test_rc}" != "0" ]; then
    remote_bundle_path="$(find_remote_failure_bundle preferred_live_bundle_path.txt || true)"
    if [ -n "${remote_bundle_path}" ]; then
        echo "[${NODE_IP}] reuse live EIO failure bundle: $(basename -- "${remote_bundle_path}")"
    else
        echo "[${NODE_IP}] no reusable live EIO bundle; collect fallback gcore/diagnostic bundle on DUT (timeout=${failure_bundle_collect_timeout_seconds}s)"
        if ! collect_fallback_failure_bundle; then
            echo "[${NODE_IP}] WARN: fallback failure bundle collection failed or timed out; keep original test exit code ${test_rc}"
        fi
        remote_bundle_path="$(find_remote_failure_bundle latest_bundle_path.txt || true)"
    fi

    if [ -n "${remote_bundle_path}" ]; then
        if ! copy_exact_failure_bundle "${remote_bundle_path}"; then
            echo "[${NODE_IP}] WARN: exact failure bundle copy failed or timed out; keep original test exit code ${test_rc}"
        fi
    else
        echo "[${NODE_IP}] WARN: no valid failure bundle path is available for copy"
    fi
fi

echo "[${NODE_IP}] copy back reports"
mkdir -p allure-results
rm -rf "${tmp_results}"
allure_copy_command="${REMOTE_SCP_COMMAND} -r ${TARGET_USER}@${NODE_IP}:${REMOTE_DIR}/allure-results ./${tmp_results}"
run_cleanup_command "copy Allure results" "${report_copy_timeout_seconds}" \
    bash -c "${allure_copy_command}" || true
if [ -d "${tmp_results}" ]; then
    run_cleanup_command "mark Allure target context" "${report_command_timeout_seconds}" \
        python3 powercycle/mark_allure_target_context.py "${tmp_results}" "${NODE_IP}" || true
    run_cleanup_command "merge Allure results" "${report_copy_timeout_seconds}" \
        cp -R "${tmp_results}/." ./allure-results/ || true
    rm -rf "${tmp_results}"
fi
report_copy_command="${REMOTE_SCP_COMMAND} ${TARGET_USER}@${NODE_IP}:${REMOTE_DIR}/report.xml ./${report_file}"
run_cleanup_command "copy merged JUnit report" "${report_copy_timeout_seconds}" \
    bash -c "${report_copy_command}" || true
if [ ! -f "${report_file}" ]; then
    # Fallback: pull known per-item reports into a temp dir, merge, then delete temp files.
    item_dir="item-junit-${NODE_IP}${report_suffix}"
    rm -rf "${item_dir}"
    mkdir -p "${item_dir}"
    item_copy_command="${REMOTE_SCP_COMMAND} ${TARGET_USER}@${NODE_IP}:${REMOTE_DIR}/report_*.xml ${item_dir}/"
    run_cleanup_command "copy per-item JUnit reports" "${report_copy_timeout_seconds}" \
        bash -c "${item_copy_command}" 2>/dev/null || true
    run_cleanup_command "merge per-item JUnit reports" "${report_command_timeout_seconds}" \
        python3 powercycle/salvage_junit_reports.py --from-dir "${item_dir}" --output "${report_file}" || true
    rm -rf "${item_dir}"
fi

if [ "${test_rc}" != "0" ]; then
    exit "${test_rc}"
fi

if [ ! -f "${report_file}" ]; then
    echo "[${NODE_IP}] ERROR: Missing ${report_file}. ${test_label} did not produce a JUnit report."

    echo "TEST_EXECUTION_STATUS=failed"

    echo "TEST_EXECUTION_EXIT_CODE=2"

    {
        echo "[${NODE_IP}] ERROR: Missing ${report_file}. ${test_label} did not produce a JUnit report."
        echo "TEST_EXECUTION_STATUS=failed"
        echo "TEST_EXECUTION_EXIT_CODE=2"
    } >>"${execution_log}"

    exit 2
fi

echo "TEST_EXECUTION_STATUS=passed"
echo "TEST_EXECUTION_STATUS=passed" >> "${execution_log}"
