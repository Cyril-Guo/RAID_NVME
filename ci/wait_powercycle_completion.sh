#!/usr/bin/env bash
set -euo pipefail

: "${NODE_IP:?NODE_IP is required}"
: "${REMOTE_DIR:?REMOTE_DIR is required}"
: "${REMOTE_SSH_COMMAND:?REMOTE_SSH_COMMAND is required}"

ITEMS_FILE="${TEST_ITEMS_FILE:-test_items.txt}"
POLL_SECONDS="${POWER_CYCLE_POLL_SECONDS:-30}"
RESULT_REL="IO_Stress/log/ResultLog"

selected_powercycle_items() {
    awk -F= '
        /^[[:space:]]*\[selection\][[:space:]]*$/ { selected=1; next }
        /^[[:space:]]*\[/ { selected=0 }
        selected {
            key=$1; value=$2
            gsub(/[[:space:]]/, "", key)
            sub(/[[:space:]]*[#;].*$/, "", value)
            gsub(/[[:space:]]/, "", value)
            value=tolower(value)
            if ((key == "reboot" || key == "dc") && (value == "yes" || value == "true" || value == "1" || value == "on")) print key
        }
    ' "$ITEMS_FILE"
}

read_item_cycles() {
    local item="$1"
    awk -F= -v wanted="$item" '
        /^[[:space:]]*\[/ {
            section=$0
            gsub(/^[[:space:]]*\[|\][[:space:]]*$/, "", section)
            next
        }
        section == wanted {
            key=$1; value=$2
            gsub(/[[:space:]]/, "", key)
            sub(/[[:space:]]*[#;].*$/, "", value)
            gsub(/[[:space:]]/, "", value)
            if (key == "FIO_CYCLES" && value ~ /^[0-9]+$/) { print value; found=1; exit }
        }
        END { if (!found) print 10 }
    ' "$ITEMS_FILE"
}

result_roots() {
    local item="$1"
    printf '%s\n' \
        "${REMOTE_DIR}/cases/${item}/${RESULT_REL}" \
        "${REMOTE_DIR}/${RESULT_REL}"
}

remote_reachable() {
    eval "${REMOTE_SSH_COMMAND} \"true\"" >/dev/null 2>&1
}

remote_log_contains() {
    local item="$1" pattern="$2" root
    while IFS= read -r root; do
        if eval "${REMOTE_SSH_COMMAND} \"grep -R -E -q -- $(printf '%q' "$pattern") '${root}' 2>/dev/null\""; then
            return 0
        fi
    done < <(result_roots "$item")
    return 1
}

item_triggered() {
    remote_log_contains "$1" "request start"
}

item_failed() {
    remote_log_contains "$1" "FIO stage failed|FIO command failed|idle watchdog timeout|Traceback|AssertionError|Power-cycle.*failed"
}

item_completed() {
    remote_log_contains "$1" "all power-cycle loops completed|Power-cycle test completed all"
}

wait_one_item() {
    local item="$1" cycles timeout_min deadline trigger_deadline remaining
    cycles=$(read_item_cycles "$item")
    timeout_min="${POWER_CYCLE_COMPLETION_TIMEOUT_MINUTES:-$((cycles * 90))}"
    deadline=$(( $(date +%s) + timeout_min * 60 ))
    trigger_deadline=$(( $(date +%s) + 600 ))
    echo "[${NODE_IP}] waiting for ${item} full power-cycle completion (cycles=${cycles}, timeout=${timeout_min}m)"

    while [ "$(date +%s)" -lt "$trigger_deadline" ]; do
        if remote_reachable; then
            if item_failed "$item"; then
                echo "[${NODE_IP}] ERROR: ${item} reported a failure before/during power-cycle" >&2
                return 1
            fi
            if item_completed "$item"; then
                echo "[${NODE_IP}] ${item} power-cycle already completed"
                return 0
            fi
            item_triggered "$item" && break
        fi
        sleep "$POLL_SECONDS"
    done

    if ! remote_reachable || ! item_triggered "$item"; then
        echo "[${NODE_IP}] ERROR: ${item} never reached power-cycle request start" >&2
        return 1
    fi

    while [ "$(date +%s)" -lt "$deadline" ]; do
        if remote_reachable; then
            if item_failed "$item"; then
                echo "[${NODE_IP}] ERROR: ${item} failed during power-cycle resume" >&2
                return 1
            fi
            if item_completed "$item"; then
                echo "[${NODE_IP}] ${item} full power-cycle completed"
                return 0
            fi
            remaining=$(( (deadline - $(date +%s)) / 60 ))
            echo "[${NODE_IP}] ${item} still running (SSH up, ~${remaining}m left)"
        else
            remaining=$(( (deadline - $(date +%s)) / 60 ))
            echo "[${NODE_IP}] ${item} host unreachable during power-cycle (~${remaining}m left)"
        fi
        sleep "$POLL_SECONDS"
    done

    echo "[${NODE_IP}] ERROR: ${item} did not complete within ${timeout_min} minutes" >&2
    return 1
}

mapfile -t selected_items < <(selected_powercycle_items)
if [ "${#selected_items[@]}" -eq 0 ]; then
    echo "[${NODE_IP}] no reboot/dc selected; skip power-cycle completion wait"
    exit 0
fi
if [ "${#selected_items[@]}" -ne 1 ]; then
    echo "[${NODE_IP}] ERROR: only one reboot/DC item may be selected" >&2
    exit 2
fi

wait_one_item "${selected_items[0]}"
