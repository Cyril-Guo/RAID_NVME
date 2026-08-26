#!/usr/bin/env bash
# Enable draid RAID1-pending style debug knobs before / during triage.
# Best-effort: probes module parameters and debugfs; never fails the caller.
set -uo pipefail

NODE_IP=${NODE_IP:-unknown}
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/.." && pwd)
REMOTE_DIR=${REMOTE_DIR:-${REPO_ROOT}}
LOG_DIR="${REMOTE_DIR}/failure_bundles"
LOG_FILE="${LOG_DIR}/draid_pending_debug.txt"

mkdir -p "${LOG_DIR}" 2>/dev/null || true
{
    echo "=== enable_draid_pending_debug $(date -Is 2>/dev/null || date) ==="
    echo "NODE_IP=${NODE_IP}"
} >"${LOG_FILE}"

log() {
    printf '[%s] %s\n' "${NODE_IP}" "$*" | tee -a "${LOG_FILE}"
}

# Mount debugfs if needed for dyndbg / draid debug nodes.
if [ ! -d /sys/kernel/debug ]; then
    mkdir -p /sys/kernel/debug 2>/dev/null || true
fi
if ! mountpoint -q /sys/kernel/debug 2>/dev/null; then
    mount -t debugfs debugfs /sys/kernel/debug 2>/dev/null || true
fi

PARAMS=/sys/module/draid/parameters
if [ -d "${PARAMS}" ]; then
    log "draid module parameters present"
    ls -la "${PARAMS}" >>"${LOG_FILE}" 2>/dev/null || true
    # Snapshot current values first.
    {
        echo "=== parameters before ==="
        for f in "${PARAMS}"/*; do
            [ -e "$f" ] || continue
            printf '%s=%s\n' "$(basename "$f")" "$(cat "$f" 2>/dev/null || echo '?')"
        done
    } >>"${LOG_FILE}"

    # Explicit common knobs (driver may expose a subset).
    for name in \
        raid1_pending_debug \
        raid1_pending_dbg \
        r1_pending_debug \
        pending_debug \
        debug_pending \
        draid_raid1_pending_debug \
        raid1_debug_pending \
        enable_raid1_pending_debug \
        pending_io_debug \
        raid1_pending
    do
        if [ -w "${PARAMS}/${name}" ]; then
            before=$(cat "${PARAMS}/${name}" 2>/dev/null || echo '?')
            if echo 1 >"${PARAMS}/${name}" 2>/dev/null; then
                after=$(cat "${PARAMS}/${name}" 2>/dev/null || echo '?')
                log "set parameters/${name}: ${before} -> ${after}"
            else
                log "WARN: failed to write parameters/${name}"
            fi
        fi
    done

    # Auto-enable writable params whose names look like RAID1/pending debug.
    for f in "${PARAMS}"/*; do
        [ -w "$f" ] || continue
        name=$(basename "$f")
        case "${name}" in
            *pending*|*raid1*debug*|*debug*raid1*|*r1*dbg*|*r1*debug*)
                before=$(cat "$f" 2>/dev/null || echo '?')
                case "${before}" in
                    0|N|n|off|OFF|false|False) ;;
                    *) continue ;;
                esac
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
if [ -w "${DYNDBG}" ]; then
    echo 'module draid +p' >"${DYNDBG}" 2>/dev/null \
        && log "dyndbg: module draid +p" \
        || log "WARN: dyndbg enable failed"
    echo 'module draid +pflmt' >"${DYNDBG}" 2>/dev/null || true
    grep -i draid "${DYNDBG}" 2>/dev/null | head -n 40 >>"${LOG_FILE}" || true
fi

# Flip on/writable debugfs files under *draid* that look like pending/raid1 debug.
find /sys/kernel/debug -maxdepth 5 \( -iname '*draid*' -o -iname '*dpraid*' \) -type f 2>/dev/null \
    | head -n 100 | while read -r f; do
    base=$(basename "$f")
    case "${base}" in
        *pending*|*raid1*debug*|*debug*)
            if [ -w "$f" ]; then
                cur=$(cat "$f" 2>/dev/null || true)
                case "${cur}" in
                    0|N|n|off|'')
                        echo 1 >"$f" 2>/dev/null \
                            && log "debugfs set ${f} -> 1" \
                            || true
                        ;;
                esac
            fi
            ;;
    esac
done

log "RAID1 pending debug enable done; log -> ${LOG_FILE}"
exit 0
