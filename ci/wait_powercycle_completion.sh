#!/usr/bin/env bash
# Wait on the Jenkins agent for reboot/dc loops to finish on the DUT.
# Pytest only verifies "request start"; multi-loop resume happens after reboot.
set -euo pipefail

: "${NODE_IP:?NODE_IP is required}"
: "${TARGET_USER:?TARGET_USER is required}"
: "${REMOTE_DIR:?REMOTE_DIR is required}"
: "${REMOTE_SSH_COMMAND:?REMOTE_SSH_COMMAND is required}"

ITEMS_FILE="${TEST_ITEMS_FILE:-test_items.txt}"
POLL_SECONDS="${POWER_CYCLE_POLL_SECONDS:-30}"
RESULT_REL="IO_Stress/log/ResultLog"

# Prefer per-case workdirs (cases/<item>/...), fall back to build-root IO_Stress.
result_roots_for_item() {
    local run_key="$1"
    printf '%s\n' \
        "${REMOTE_DIR}/cases/${run_key}/${RESULT_REL}" \
        "${REMOTE_DIR}/${RESULT_REL}"
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

read_item_cycles() {
    local item="$1"
    local in_section=0
    local line key value
    local cycles=""
    [[ -f "${ITEMS_FILE}" ]] || { echo 10; return; }
    while IFS= read -r line || [[ -n "${line}" ]]; do
        line="${line%%#*}"
        line="$(echo "${line}" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
        [[ -z "${line}" ]] && continue
        if [[ "${line}" =~ ^\[(.+)\]$ ]]; then
            if [[ "${BASH_REMATCH[1]}" == "${item}" ]]; then
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
    local log_name text root
    log_name="$(powercycle_log_name "${item}")"
    while IFS= read -r root; do
        # shellcheck disable=SC2086
        text="$(eval ${REMOTE_SSH_COMMAND} "grep -F 'all power-cycle loops completed' ${root}/${log_name} 2>/dev/null" || true)"
        if [[ -n "${text}" ]]; then
            return 0
        fi
        # Resume path prints this after reboot_rc=2.
        # shellcheck disable=SC2086
        text="$(eval ${REMOTE_SSH_COMMAND} "grep -F 'Power-cycle test completed all' ${root}/powercycle_resume.log 2>/dev/null" || true)"
        if [[ -n "${text}" ]]; then
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

wait_one_item() {
    local run_key="$1"
    local item="${run_key%%__*}"
    local cycles timeout_min deadline now remaining
    cycles="$(read_item_cycles "${item}")"
    # Default budget: each loop can include long FIO (CSV 3600s) + reboot/boot margin.
    timeout_min="${POWER_CYCLE_COMPLETION_TIMEOUT_MINUTES:-$((cycles * 90))}"
    deadline=$(( $(date +%s) + timeout_min * 60 ))

    echo "[${NODE_IP}] waiting for ${item} powercycle completion (cycles=${cycles}, timeout=${timeout_min}m)"

    # Fast path: never triggered (e.g. skipped earlier) -> do not burn full timeout.
    local saw_trigger=0
    local trigger_deadline=$(( $(date +%s) + 600 ))
    while [ "$(date +%s)" -lt "${trigger_deadline}" ]; do
        if remote_reachable && item_triggered "${run_key}"; then
            saw_trigger=1
            break
        fi
        if item_completed "${run_key}"; then
            echo "[${NODE_IP}] ${item} already completed"
            return 0
        fi
        sleep "${POLL_SECONDS}"
    done

    if [[ "${saw_trigger}" -ne 1 ]]; then
        echo "[${NODE_IP}] ERROR: ${item} never reached request start; cannot close powercycle loop" >&2
        return 1
    fi

    while [ "$(date +%s)" -lt "${deadline}" ]; do
        if remote_reachable && item_completed "${run_key}"; then
            echo "[${NODE_IP}] ${item} powercycle completed"
            return 0
        fi
        now=$(date +%s)
        remaining=$(( (deadline - now) / 60 ))
        if remote_reachable; then
            echo "[${NODE_IP}] ${item} still running (SSH up, ~${remaining}m left)"
        else
            echo "[${NODE_IP}] ${item} host unreachable during powercycle (~${remaining}m left)"
        fi
        sleep "${POLL_SECONDS}"
    done

    echo "[${NODE_IP}] ERROR: ${item} powercycle did not complete within ${timeout_min} minutes" >&2
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
