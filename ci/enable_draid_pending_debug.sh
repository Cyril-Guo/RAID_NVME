#!/usr/bin/env bash
# Enable draid RAID1-pending style debug knobs before / during triage.
# Best-effort: probes module parameters and debugfs; never fails the caller.
#
# Safety:
#   - Only write known *_debug / *_dbg / enable_* boolean-style knobs (whitelist).
#   - Do NOT blindly write 1 into arbitrary *pending* counters/bitmaps.
#   - dyndbg defaults to +p only; set DRAID_DYNDBG=full for +pflmt, or 0 to skip.
set -uo pipefail

NODE_IP=${NODE_IP:-unknown}
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/.." && pwd)
REMOTE_DIR=${REMOTE_DIR:-${REPO_ROOT}}
LOG_DIR="${REMOTE_DIR}/failure_bundles"
LOG_FILE="${LOG_DIR}/draid_pending_debug.txt"
# p | full | 0/off/no
DRAID_DYNDBG=${DRAID_DYNDBG:-p}

mkdir -p "${LOG_DIR}" 2>/dev/null || true
{
    echo "=== enable_draid_pending_debug $(date -Is 2>/dev/null || date) ==="
    echo "NODE_IP=${NODE_IP}"
    echo "DRAID_DYNDBG=${DRAID_DYNDBG}"
} >"${LOG_FILE}"

log() {
    printf '[%s] %s\n' "${NODE_IP}" "$*" | tee -a "${LOG_FILE}"
}

is_off_value() {
    case "${1:-}" in
        0|N|n|off|OFF|false|False|'') return 0 ;;
        *) return 1 ;;
    esac
}

# Mount debugfs if needed for dyndbg / draid debug nodes.
if [ ! -d /sys/kernel/debug ]; then
    mkdir -p /sys/kernel/debug 2>/dev/null || true
fi
if ! mountpoint -q /sys/kernel/debug 2>/dev/null; then
    mount -t debugfs debugfs /sys/kernel/debug 2>/dev/null || true
fi

# Boolean-style debug knobs only (never counters like raid1_pending).
WHITELIST_PARAMS=(
    raid1_pending_debug
    raid1_pending_dbg
    r1_pending_debug
    pending_debug
    debug_pending
    draid_raid1_pending_debug
    raid1_debug_pending
    enable_raid1_pending_debug
    pending_io_debug
)

PARAMS=/sys/module/draid/parameters
if [ -d "${PARAMS}" ]; then
    log "draid module parameters present"
    ls -la "${PARAMS}" >>"${LOG_FILE}" 2>/dev/null || true
    {
        echo "=== parameters before ==="
        for f in "${PARAMS}"/*; do
            [ -e "$f" ] || continue
            printf '%s=%s\n' "$(basename "$f")" "$(cat "$f" 2>/dev/null || echo '?')"
        done
    } >>"${LOG_FILE}"

    for name in "${WHITELIST_PARAMS[@]}"; do
        if [ -w "${PARAMS}/${name}" ]; then
            before=$(cat "${PARAMS}/${name}" 2>/dev/null || echo '?')
            if ! is_off_value "${before}" && [ "${before}" != "?" ]; then
                log "skip parameters/${name}: already ${before}"
                continue
            fi
            if echo 1 >"${PARAMS}/${name}" 2>/dev/null; then
                after=$(cat "${PARAMS}/${name}" 2>/dev/null || echo '?')
                log "set parameters/${name}: ${before} -> ${after}"
            else
                log "WARN: failed to write parameters/${name}"
            fi
        fi
    done

    # Also enable writable params whose names clearly look like debug flags
    # (*_debug / *_dbg / enable_*debug*), not bare *pending* counters.
    for f in "${PARAMS}"/*; do
        [ -w "$f" ] || continue
        name=$(basename "$f")
        case "${name}" in
            *_debug|*_dbg|enable_*debug*|enable_*dbg*)
                before=$(cat "$f" 2>/dev/null || echo '?')
                if ! is_off_value "${before}"; then
                    continue
                fi
                if echo 1 >"$f" 2>/dev/null; then
                    after=$(cat "$f" 2>/dev/null || echo '?')
                    log "auto-enabled parameters/${name}: ${before} -> ${after}"
                fi
                ;;
        esac
    done

    {
        echo "=== parameters after ==="
        for f in "${PARAMS}"/*; do
            [ -e "$f" ] || continue
            printf '%s=%s\n' "$(basename "$f")" "$(cat "$f" 2>/dev/null || echo '?')"
        done
    } >>"${LOG_FILE}"
else
    log "WARN: /sys/module/draid/parameters missing (module not loaded?)"
fi

# Turn on dynamic debug printks for draid if available.
DYNDBG=/sys/kernel/debug/dynamic_debug/control
case "${DRAID_DYNDBG}" in
    0|off|OFF|no|NO|false|False)
        log "dyndbg skipped (DRAID_DYNDBG=${DRAID_DYNDBG})"
        ;;
    full|FULL|pflmt)
        if [ -w "${DYNDBG}" ]; then
            echo 'module draid +pflmt' >"${DYNDBG}" 2>/dev/null \
                && log "dyndbg: module draid +pflmt" \
                || log "WARN: dyndbg enable failed"
            grep -i draid "${DYNDBG}" 2>/dev/null | head -n 40 >>"${LOG_FILE}" || true
        fi
        ;;
    *)
        # Default: +p only (less dmesg spam than +pflmt).
        if [ -w "${DYNDBG}" ]; then
            echo 'module draid +p' >"${DYNDBG}" 2>/dev/null \
                && log "dyndbg: module draid +p" \
                || log "WARN: dyndbg enable failed"
            grep -i draid "${DYNDBG}" 2>/dev/null | head -n 40 >>"${LOG_FILE}" || true
        fi
        ;;
esac

# Flip on writable debugfs files under *draid* that look like *debug* flags only.
find /sys/kernel/debug -maxdepth 5 \( -iname '*draid*' -o -iname '*dpraid*' \) -type f 2>/dev/null \
    | head -n 100 | while read -r f; do
    base=$(basename "$f")
    case "${base}" in
        *pending*debug*|*raid1*debug*|*_debug|*_dbg)
            if [ -w "$f" ]; then
                cur=$(cat "$f" 2>/dev/null || true)
                if is_off_value "${cur}"; then
                    echo 1 >"$f" 2>/dev/null \
                        && log "debugfs set ${f} -> 1" \
                        || true
                fi
            fi
            ;;
    esac
done

log "RAID1 pending debug enable done; log -> ${LOG_FILE}"
exit 0
