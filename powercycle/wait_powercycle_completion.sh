#!/usr/bin/env bash
# Wait on the Jenkins agent for reboot/dc loops to finish on the DUT.
# Pytest only verifies "request start"; multi-loop resume happens after reboot.
set -euo pipefail

: "${NODE_IP:?NODE_IP is required}"
: "${TARGET_USER:?TARGET_USER is required}"
: "${REMOTE_DIR:?REMOTE_DIR is required}"
: "${REMOTE_SSH_COMMAND:?REMOTE_SSH_COMMAND is required}"

ITEMS_FILE="${TEST_ITEMS_FILE:-test_items.txt}"
POLL_SECONDS="${POWER_CYCLE_POLL_SECONDS:-15}"
RESULT_REL="IO_Stress/log/ResultLog"

# Prefer per-case workdir when it exists on DUT; otherwise use build-root only.
# Watching both always can false-complete/fail on stale build-root markers.
result_roots_for_item() {
    local run_key="$1"
    local case_root="${REMOTE_DIR}/cases/${run_key}/${RESULT_REL}"
    local build_root="${REMOTE_DIR}/${RESULT_REL}"
    # shellcheck disable=SC2086
    if eval ${REMOTE_SSH_COMMAND} "test -d $(printf '%q' "${case_root}")" >/dev/null 2>&1; then
        printf '%s\n' "${case_root}"
        return 0
    fi
    printf '%s\n' "${build_root}"
}

# test_powercycle_01_reboot -> reboot; plain reboot stays reboot.
item_short_name() {
    local name="$1"
    if [[ "${name}" =~ ^test_powercycle_[0-9]+_(.+)$ ]]; then
        printf '%s\n' "${BASH_REMATCH[1]}"
    else
        printf '%s\n' "${name}"
    fi
}

is_powercycle_item() {
    local short
    short="$(item_short_name "$1")"
    case "${short}" in
        reboot|dc) return 0 ;;
        *) return 1 ;;
    esac
}

powercycle_log_name() {
    local short
    short="$(item_short_name "$1")"
    if [[ "${short}" == "reboot" ]]; then
        printf '%s\n' "reboot_command.log"
    else
        printf '%s\n' "dc_command.log"
    fi
}

selected_run_keys=()
parse_selected_powercycle_items() {
    local in_selection=0
    local line name order token
    local -a tokens=()
    selected_run_keys=()
    [[ -f "${ITEMS_FILE}" ]] || return 0
    while IFS= read -r line || [[ -n "${line}" ]]; do
        case "${line}" in
            *"BEGIN SELECTION"*)
                in_selection=1
                continue
                ;;
            *"END SELECTION"*)
                in_selection=0
                continue
                ;;
        esac
        [[ "${in_selection}" -eq 1 ]] || continue
        [[ "${line}" =~ ^[[:space:]]*# ]] && continue
        # shellcheck disable=SC2086
        set -- ${line}
        tokens=("$@")
        [[ "${#tokens[@]}" -ge 1 ]] || continue

        # Preferred: test_powercycle_01_reboot 1   (name then one-or-more orders)
        # Also accept short reboot/dc and order-first: 1 test_powercycle_01_reboot
        local i
        name=""
        if [[ "${tokens[0]}" =~ ^[0-9]+$ ]]; then
            name="${tokens[$((${#tokens[@]} - 1))]}"
            if ! is_powercycle_item "${name}"; then
                continue
            fi
            for ((i = 0; i < ${#tokens[@]} - 1; i++)); do
                token="${tokens[$i]}"
                if [[ "${token}" =~ ^[0-9]+$ ]]; then
                    selected_run_keys+=("${name}__${token}")
                fi
            done
            continue
        fi

        name="${tokens[0]}"
        if ! is_powercycle_item "${name}"; then
            continue
        fi
        for ((i = 1; i < ${#tokens[@]}; i++)); do
            order="${tokens[$i]}"
            if [[ "${order}" =~ ^[0-9]+$ ]]; then
                selected_run_keys+=("${name}__${order}")
            fi
        done
    done < "${ITEMS_FILE}"
}

read_item_ignore_error() {
    local item="$1"
    local want_short in_section=0
    local line key value section=""
    local ignore=""
    want_short="$(item_short_name "${item}")"
    [[ -f "${ITEMS_FILE}" ]] || { echo "no"; return; }
    while IFS= read -r line || [[ -n "${line}" ]]; do
        line="${line%%#*}"
        line="$(echo "${line}" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
        [[ -z "${line}" ]] && continue
        if [[ "${line}" =~ ^\[(.+)\]$ ]]; then
            section="${BASH_REMATCH[1]}"
            if [[ "${section}" == "${item}" ]] || [[ "$(item_short_name "${section}")" == "${want_short}" ]]; then
                in_section=1
            else
                in_section=0
            fi
            continue
        fi
        [[ "${in_section}" -eq 1 ]] || continue
        key="$(echo "${line%%=*}" | sed 's/[[:space:]]//g')"
        value="$(echo "${line#*=}" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
        if [[ "${key}" == "IGNORE_ERROR" ]]; then
            ignore="$(echo "${value}" | tr '[:upper:]' '[:lower:]')"
        fi
    done < "${ITEMS_FILE}"
    if [[ "${ignore}" == "yes" ]]; then
        echo "yes"
    else
        echo "no"
    fi
}

read_item_cycles() {
    local item="$1"
    local want_short in_section=0
    local line key value section=""
    local cycles=""
    want_short="$(item_short_name "${item}")"
    [[ -f "${ITEMS_FILE}" ]] || { echo 10; return; }
    while IFS= read -r line || [[ -n "${line}" ]]; do
        line="${line%%#*}"
        line="$(echo "${line}" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
        [[ -z "${line}" ]] && continue
        if [[ "${line}" =~ ^\[(.+)\]$ ]]; then
            section="${BASH_REMATCH[1]}"
            if [[ "${section}" == "${item}" ]] || [[ "$(item_short_name "${section}")" == "${want_short}" ]]; then
                in_section=1
            else
                in_section=0
            fi
            continue
        fi
        [[ "${in_section}" -eq 1 ]] || continue
        key="$(echo "${line%%=*}" | sed 's/[[:space:]]//g')"
        value="$(echo "${line#*=}" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
        if [[ "${key}" == "FIO_CYCLES" ]]; then
            cycles="${value}"
        fi
    done < "${ITEMS_FILE}"
    if [[ "${cycles}" =~ ^[0-9]+$ ]]; then
        echo "${cycles}"
    else
        echo 10
    fi
}

remote_grep() {
    local pattern="$1"
    local run_key="${2:-}"
    local root
    if [[ -n "${run_key}" ]]; then
        while IFS= read -r root; do
            # shellcheck disable=SC2086
            eval ${REMOTE_SSH_COMMAND} "grep -R -F -e $(printf '%q' "${pattern}") ${root} 2>/dev/null" || true
        done < <(result_roots_for_item "${run_key}")
        return 0
    fi
    # shellcheck disable=SC2086
    eval ${REMOTE_SSH_COMMAND} "grep -R -F -e $(printf '%q' "${pattern}") ${REMOTE_DIR}/${RESULT_REL} 2>/dev/null" || true
}

remote_reachable() {
    # shellcheck disable=SC2086
    eval ${REMOTE_SSH_COMMAND} "true" >/dev/null 2>&1
}

item_completed() {
    local run_key="$1"
    local item="${run_key%%__*}"
    local log_name text root cycles last_loop
    log_name="$(powercycle_log_name "${item}")"
    cycles="$(read_item_cycles "${item}")"
    while IFS= read -r root; do
        # IMPORTANT: redirect local ssh/sshpass stderr too. During reboot, connection
        # errors on stdout/stderr must NOT be treated as completion markers.
        # Also require the literal marker substring (not merely non-empty output).
        # shellcheck disable=SC2086
        text="$(eval ${REMOTE_SSH_COMMAND} "grep -F 'all power-cycle loops completed' $(printf '%q' "${root}/${log_name}")" 2>/dev/null || true)"
        if [[ "${text}" == *"all power-cycle loops completed"* ]]; then
            # Cross-check reboot.log progress when available (LOOP from test_items).
            # shellcheck disable=SC2086
            last_loop="$(eval ${REMOTE_SSH_COMMAND} "awk 'NF && \$1 ~ /^[0-9]+\$/ { n=\$1 } END { print n+0 }' $(printf '%q' "${root}/reboot.log")" 2>/dev/null || true)"
            if [[ "${cycles}" =~ ^[0-9]+$ && "${last_loop}" =~ ^[0-9]+$ ]]; then
                if [[ "${last_loop}" -lt "${cycles}" ]]; then
                    echo "[${NODE_IP}] $(date '+%F %T') ignore premature completion marker (reboot.log loop=${last_loop} < cycles=${cycles})" >&2
                    continue
                fi
            fi
            return 0
        fi
        # Resume path prints this after reboot_rc=10.
        # shellcheck disable=SC2086
        text="$(eval ${REMOTE_SSH_COMMAND} "grep -F 'Power-cycle test completed all' $(printf '%q' "${root}/powercycle_resume.log")" 2>/dev/null || true)"
        if [[ "${text}" == *"Power-cycle test completed all"* ]]; then
            # shellcheck disable=SC2086
            last_loop="$(eval ${REMOTE_SSH_COMMAND} "awk 'NF && \$1 ~ /^[0-9]+\$/ { n=\$1 } END { print n+0 }' $(printf '%q' "${root}/reboot.log")" 2>/dev/null || true)"
            if [[ "${cycles}" =~ ^[0-9]+$ && "${last_loop}" =~ ^[0-9]+$ ]]; then
                if [[ "${last_loop}" -lt "${cycles}" ]]; then
                    echo "[${NODE_IP}] $(date '+%F %T') ignore premature resume completion (reboot.log loop=${last_loop} < cycles=${cycles})" >&2
                    continue
                fi
            fi
            return 0
        fi
    done < <(result_roots_for_item "${run_key}")
    return 1
}

item_triggered() {
    local run_key="$1"
    local item="${run_key%%__*}"
    local log_name pattern text root
    log_name="$(powercycle_log_name "${item}")"
    pattern="request start"
    while IFS= read -r root; do
        # shellcheck disable=SC2086
        text="$(eval ${REMOTE_SSH_COMMAND} "grep -F $(printf '%q' "${pattern}") ${root}/${log_name} 2>/dev/null" || true)"
        if [[ -n "${text}" ]]; then
            return 0
        fi
    done < <(result_roots_for_item "${run_key}")
    return 1
}


item_failed() {
    local run_key="$1"
    local item="${run_key%%__*}"
    local log_name root ignore_error match_file match_line
    local -a patterns=(
        "FIO stage failed"
        "FIO stage abort"
        "FIO command failed"
        "FIO failed"
        "verify failed"
        "Refuse to run"
        "No non-system test disk found"
        "Fail to detect system disk"
        "idle watchdog timeout"
        "PowerCycle FIO requires filename="
        "Power-cycle reboot/dc command failed"
        "stop_flag is STOP,so exit"
        "Power-cycle abort after commit"
        "the input log_interval isn't a number"
        "Invalid arguments"
        "Invalid flag="
        "Unsupport test type"
        "the input S0 delay time isn't a number"
        "the input runtime isn't a number"
        "the input LOOP isn't a number"
        "the input S5 delay time isn't a number"
        "the DC mode isn't supported"
        "Failed to generate random powercycle plan"
        "Failed to detect test disk size"
        "Specified disk contains system disk"
        "PowerCycle run_fio.sh only supports"
        "powercycle_direct.sh only supports"
        "unexpected do_reboot rc="
        "reached unexpected fallthrough"
    )
    # MachineCheck soft-continue (IGNORE_ERROR=yes / NON-STOP) must NOT fail the wait loop.
    ignore_error="$(read_item_ignore_error "${item}")"
    if [[ "${ignore_error}" != "yes" ]]; then
        patterns+=(
            "ERROR: MachineCheck before FIO failed"
            "ERROR: MachineCheck inconsistencies found"
            "ERROR: MachineCheck Log Inconsistency"
            "Whitelist field differences"
        )
    fi
    log_name="$(powercycle_log_name "${item}")"

    # IMPORTANT: only inspect runtime logs under ResultLog.
    # Never recursive-grep the workspace — unit tests / run_fio.sh source contain
    # the literal string "FIO stage failed" and caused false FAILURE (PowerCycle #1).
    while IFS= read -r root; do
        # Explicit abort marker file (STOP-after-commit).
        # shellcheck disable=SC2086
        text="$(eval ${REMOTE_SSH_COMMAND} "test -f $(printf '%q' "${root}/powercycle_abort_after_commit") && printf FOUND" 2>/dev/null || true)"
        if [[ "${text}" == *FOUND* ]]; then
            echo "[${NODE_IP}] $(date '+%F %T') detected failure marker in ${item}: powercycle_abort_after_commit (${root}/powercycle_abort_after_commit)" >&2
            return 0
        fi
        local -a files=(
            "${root}/${log_name}"
            "${root}/powercycle_resume.log"
            "${root}/fio_result/result.log"
            "${root}/result.log"
        )
        local f pattern
        for f in "${files[@]}"; do
            for pattern in "${patterns[@]}"; do
                # shellcheck disable=SC2086
                match_line="$(eval ${REMOTE_SSH_COMMAND} "grep -F $(printf '%q' "${pattern}") $(printf '%q' "${f}") | tail -n 1" 2>/dev/null || true)"
                if [[ "${match_line}" == *"${pattern}"* ]]; then
                    # If VERIFY later recovered, ignore retryable markers that may remain from soft attempts.
                    # Final hard failure always writes "FIO stage failed" which is never ignored.
                    if [[ "${pattern}" == "FIO stage abort" || "${pattern}" == "FIO command failed" || "${pattern}" == "verify failed" || "${pattern}" == "FIO failed" ]]; then
                        recovered="$(eval ${REMOTE_SSH_COMMAND} "grep -F 'VERIFY' $(printf '%q' "${f}") 2>/dev/null | grep -F 'recovered' | tail -n 1" || true)"
                        hard="$(eval ${REMOTE_SSH_COMMAND} "grep -F 'FIO stage failed' $(printf '%q' "${f}") 2>/dev/null | tail -n 1" || true)"
                        if [[ -n "${recovered}" && -z "${hard}" ]]; then
                            echo "[${NODE_IP}] $(date '+%F %T') ignore soft failure marker after VERIFY recovered: ${pattern}" >&2
                            continue
                        fi
                    fi
                    echo "[${NODE_IP}] $(date '+%F %T') detected failure marker in ${item}: ${pattern}" >&2
                    echo "[${NODE_IP}]   file: ${f}" >&2
                    echo "[${NODE_IP}]   line: ${match_line}" >&2
                    return 0
                fi
            done
        done
    done < <(result_roots_for_item "${run_key}")
    return 1
}



stream_state_dir() {
    local run_key="$1"
    local safe
    safe="$(printf '%s' "${NODE_IP}_${run_key}" | tr -c 'A-Za-z0-9._-' '_')"
    printf '%s\n' "/tmp/pc_wait_stream_${safe}"
}

# Print only NEW bytes from a remote runtime log into Jenkins console.
stream_remote_file() {
    local run_key="$1"
    local label="$2"
    local remote_file="$3"
    local state_dir chunk_file offset_file size offset got
    state_dir="$(stream_state_dir "${run_key}")"
    mkdir -p "${state_dir}"
    chunk_file="${state_dir}/${label//\//_}.chunk"
    offset_file="${state_dir}/${label//\//_}.offset"
    offset=0
    if [[ -f "${offset_file}" ]]; then
        offset="$(tr -d '[:space:]' < "${offset_file}" || true)"
        [[ "${offset}" =~ ^[0-9]+$ ]] || offset=0
    fi

    # shellcheck disable=SC2086
    size="$(eval ${REMOTE_SSH_COMMAND} "if test -f $(printf '%q' "${remote_file}"); then wc -c < $(printf '%q' "${remote_file}"); else echo 0; fi" 2>/dev/null | tr -d '[:space:]' || true)"
    [[ "${size}" =~ ^[0-9]+$ ]] || size=0
    if [[ "${size}" -lt "${offset}" ]]; then
        offset=0
    fi
    if [[ "${size}" -le "${offset}" ]]; then
        return 0
    fi

    # shellcheck disable=SC2086
    eval ${REMOTE_SSH_COMMAND} "dd if=$(printf '%q' "${remote_file}") bs=1 skip=${offset} status=none 2>/dev/null || tail -c +$((offset + 1)) $(printf '%q' "${remote_file}") 2>/dev/null" \
        >"${chunk_file}" 2>/dev/null || true
    if [[ ! -s "${chunk_file}" ]]; then
        return 0
    fi
    while IFS= read -r line || [[ -n "${line}" ]]; do
        printf '[%s] [%s] %s\n' "${NODE_IP}" "${label}" "${line}"
    done <"${chunk_file}"
    got="$(wc -c <"${chunk_file}" | tr -d '[:space:]')"
    [[ "${got}" =~ ^[0-9]+$ ]] || got=0
    offset=$((offset + got))
    printf '%s\n' "${offset}" >"${offset_file}"
}

stream_all_runtime_logs() {
    local run_key="$1"
    local item="${run_key%%__*}"
    local log_name root
    log_name="$(powercycle_log_name "${item}")"
    while IFS= read -r root; do
        stream_remote_file "${run_key}" "${log_name}" "${root}/${log_name}"
        stream_remote_file "${run_key}" "powercycle_resume.log" "${root}/powercycle_resume.log"
        stream_remote_file "${run_key}" "fio_result/result.log" "${root}/fio_result/result.log"
        stream_remote_file "${run_key}" "reboot.log" "${root}/reboot.log"
    done < <(result_roots_for_item "${run_key}")
}

dump_remote_failure_bundle() {
    local run_key="$1"
    local item="${run_key%%__*}"
    local log_name root
    log_name="$(powercycle_log_name "${item}")"
    echo "[${NODE_IP}] $(date '+%F %T') ==== FAILURE BUNDLE begin run_key=${run_key} ===="
    stream_all_runtime_logs "${run_key}"
    while IFS= read -r root; do
        echo "[${NODE_IP}] $(date '+%F %T') ---- failure dump root=${root} ----"
        # shellcheck disable=SC2086
        eval ${REMOTE_SSH_COMMAND} "
echo '[${log_name} last 200]';
tail -n 200 $(printf '%q' "${root}/${log_name}") 2>/dev/null || true
echo '[powercycle_resume.log last 400]';
tail -n 400 $(printf '%q' "${root}/powercycle_resume.log") 2>/dev/null || true
echo '[fio_result/result.log last 300]';
tail -n 300 $(printf '%q' "${root}/fio_result/result.log") 2>/dev/null || true
echo '[machine_diff_error.log]';
tail -n 160 \$(dirname $(printf '%q' "${root}"))/../TestErrorLog/machine_diff_error.log 2>/dev/null || true
echo '[latest detresult tails]';
ls -1t $(printf '%q' "${root}/fio_result/detresult")/*.txt 2>/dev/null | head -n 5 | while read -r f; do
  echo \"---- \$f ----\"
  tail -n 100 \"\$f\" 2>/dev/null || true
done
" || true
    done < <(result_roots_for_item "${run_key}")
    echo "[${NODE_IP}] $(date '+%F %T') ==== FAILURE BUNDLE end ===="
}

dump_remote_progress() {
    local run_key="$1"
    local item="${run_key%%__*}"
    local log_name root
    log_name="$(powercycle_log_name "${item}")"
    while IFS= read -r root; do
        echo "[${NODE_IP}] $(date '+%F %T') ---- progress snapshot root=${root} ----"
        # shellcheck disable=SC2086
        # Prefer bash -lc so remote pipes/tails work; print (missing) instead of blank.

        eval ${REMOTE_SSH_COMMAND} "bash -lc $(printf '%q' "set +e; echo '[ls]'; ls -la ${root} 2>/dev/null | sed -n '1,40p'; echo '[${log_name} tail]'; tail -n 40 ${root}/${log_name} 2>/dev/null || echo '(missing)'; echo '[resume tail]'; tail -n 40 ${root}/powercycle_resume.log 2>/dev/null || echo '(missing)'; echo '[result tail]'; tail -n 40 ${root}/fio_result/result.log 2>/dev/null || echo '(missing)'; echo '[reboot.log]'; cat ${root}/reboot.log 2>/dev/null || echo '(missing)'")" || true
    done < <(result_roots_for_item "${run_key}")
}

wait_one_item() {
    local run_key="$1"
    local item="${run_key%%__*}"
    local cycles timeout_min deadline now remaining elapsed started
    cycles="$(read_item_cycles "${item}")"
    # Auto plan budget per loop: FILL windows + STRESS + VERIFY + reboot/DC boot margin.
    # Override with POWER_CYCLE_COMPLETION_TIMEOUT_MINUTES when needed.
    timeout_min="${POWER_CYCLE_COMPLETION_TIMEOUT_MINUTES:-$((cycles * 30))}"
    started=$(date +%s)
    deadline=$(( started + timeout_min * 60 ))
    local trigger_window="${POWER_CYCLE_TRIGGER_CONFIRM_SECONDS:-1800}"
    local poll="${POLL_SECONDS}"

    echo "[${NODE_IP}] $(date '+%F %T') waiting for ${item} powercycle completion (run_key=${run_key}, cycles=${cycles}, timeout=${timeout_min}m, poll=${poll}s)"
    dump_remote_progress "${run_key}"

    # Confirm trigger via request-start marker (or completion/failure).
    # Unreachable-as-trigger is gated: Jenkins sets POWER_CYCLE_ALLOW_UNREACHABLE_TRIGGER=1
    # after pytest already confirmed request start. Otherwise wrong IP would burn the full timeout.
    local saw_trigger=0
    local allow_unreachable_trigger="${POWER_CYCLE_ALLOW_UNREACHABLE_TRIGGER:-0}"
    local trigger_deadline=$(( $(date +%s) + trigger_window ))
    local round=0
    while [ "$(date +%s)" -lt "${trigger_deadline}" ]; do
        round=$((round + 1))
        now=$(date +%s)
        elapsed=$(( now - started ))
        remaining=$(( (trigger_deadline - now) ))
        if item_completed "${run_key}"; then
            echo "[${NODE_IP}] $(date '+%F %T') ${item} already completed (elapsed=${elapsed}s)"
            return 0
        fi
        if remote_reachable; then
            echo "[${NODE_IP}] $(date '+%F %T') trigger-check #${round}: SSH up, elapsed=${elapsed}s, trigger_window_left=${remaining}s"
            stream_all_runtime_logs "${run_key}"
            if item_failed "${run_key}"; then
                echo "[${NODE_IP}] $(date '+%F %T') ERROR: ${item} failed before/during powercycle" >&2
                dump_remote_failure_bundle "${run_key}"
                return 1
            fi
            if item_triggered "${run_key}"; then
                saw_trigger=1
                echo "[${NODE_IP}] $(date '+%F %T') ${item} trigger confirmed (request start)"
                break
            fi
            echo "[${NODE_IP}] $(date '+%F %T') ${item} SSH up but request-start not seen yet"
            if (( round % 3 == 0 )); then
                dump_remote_progress "${run_key}"
            fi
        else
            if [[ "${allow_unreachable_trigger}" == "1" ]]; then
                saw_trigger=1
                echo "[${NODE_IP}] $(date '+%F %T') ${item} host unreachable; treat powercycle as triggered (ALLOW_UNREACHABLE_TRIGGER=1)"
                break
            fi
            echo "[${NODE_IP}] $(date '+%F %T') trigger-check #${round}: host unreachable; waiting (set POWER_CYCLE_ALLOW_UNREACHABLE_TRIGGER=1 after pytest), elapsed=${elapsed}s"
        fi
        sleep "${poll}"
    done

    if [[ "${saw_trigger}" -ne 1 ]]; then
        echo "[${NODE_IP}] $(date '+%F %T') ERROR: ${item} never reached request start; cannot close powercycle loop" >&2
        dump_remote_failure_bundle "${run_key}"
        return 1
    fi

    round=0
    while [ "$(date +%s)" -lt "${deadline}" ]; do
        round=$((round + 1))
        now=$(date +%s)
        elapsed=$(( now - started ))
        remaining=$(( (deadline - now) / 60 ))
        remaining_s=$(( deadline - now ))
        if remote_reachable; then
            if item_failed "${run_key}"; then
                echo "[${NODE_IP}] $(date '+%F %T') ERROR: ${item} failed during powercycle (elapsed=${elapsed}s)" >&2
                dump_remote_failure_bundle "${run_key}"
                return 1
            fi
            if item_completed "${run_key}"; then
                echo "[${NODE_IP}] $(date '+%F %T') ${item} powercycle completed (elapsed=${elapsed}s)"
                stream_all_runtime_logs "${run_key}"
                dump_remote_progress "${run_key}"
                return 0
            fi
            echo "[${NODE_IP}] $(date '+%F %T') wait #${round}: ${item} still running (SSH up, elapsed=${elapsed}s, ~${remaining}m/${remaining_s}s left)"
            stream_all_runtime_logs "${run_key}"
        else
            echo "[${NODE_IP}] $(date '+%F %T') wait #${round}: ${item} host unreachable during powercycle (elapsed=${elapsed}s, ~${remaining}m/${remaining_s}s left)"
        fi
        if (( round % 4 == 0 )); then
            dump_remote_progress "${run_key}"
        fi
        sleep "${poll}"
    done

    echo "[${NODE_IP}] $(date '+%F %T') ERROR: ${item} powercycle did not complete within ${timeout_min} minutes" >&2
    dump_remote_failure_bundle "${run_key}"
    return 1
}


parse_selected_powercycle_items
if [[ "${#selected_run_keys[@]}" -eq 0 ]]; then
    echo "[${NODE_IP}] no reboot/dc selected; skip powercycle completion wait"
    exit 0
fi

rc=0
for run_key in "${selected_run_keys[@]}"; do
    if ! wait_one_item "${run_key}"; then
        rc=1
    fi
done
exit "${rc}"
