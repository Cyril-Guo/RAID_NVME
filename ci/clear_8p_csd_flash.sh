#!/usr/bin/env bash
set -euo pipefail

# Clear CSD flash+cache via dpraid on each controller reported by `dpraid show`.
# Expected show table (header + rows):
#   ID CONTROLLER MODEL ... SERIAL NUMBER ... NUMA STAT FW_VER DRIVER_VER
#   0  DAPUSTOR ...         SN-...            0    Optimal ...
#   1  DAPUSTOR ...         SN-...            0    Optimal ...
# One controller -> /c0; two -> /c0 and /c1.

NODE_IP=${NODE_IP:-unknown}
DPRAID_BIN=${DPRAID_BIN:-dpraid}

banner() {
    echo ""
    echo "[${NODE_IP}] ========== $* =========="
}

ok() {
    echo "[${NODE_IP}] [OK] $*"
}

fail() {
    echo "[${NODE_IP}] [FAIL] $*" >&2
}

if ! command -v "${DPRAID_BIN}" >/dev/null 2>&1 && [ ! -x "${DPRAID_BIN}" ]; then
    fail "dpraid command not found (PATH=${PATH})"
    exit 1
fi

banner "CSD flash+cache clear (dpraid)"
echo "[${NODE_IP}] plan: dpraid show -> parse controller IDs -> flash-clear --with-cache --force on each /cX"

banner "1/2 dpraid show (discover controllers)"
echo "[${NODE_IP}] cmd: ${DPRAID_BIN} show"
set +e
show_output="$("${DPRAID_BIN}" show 2>&1)"
show_rc=$?
set -e
printf '%s\n' "${show_output}"
if [ "${show_rc}" -ne 0 ]; then
    fail "dpraid show failed (rc=${show_rc})"
    echo "[${NODE_IP}] hint: is dpraid installed and draid loaded?" >&2
    exit 1
fi
ok "dpraid show finished"

# Only parse the controller table after the "CONTROLLER MODEL" header.
# Do not treat other numeric-leading rows (e.g. DID lists) as controllers.
mapfile -t controller_ids < <(
    printf '%s\n' "${show_output}" | awk '
        BEGIN { in_table = 0 }
        toupper($0) ~ /CONTROLLER[[:space:]]+MODEL/ {
            in_table = 1
            next
        }
        in_table && $1 ~ /^[0-9]+$/ { print $1; next }
        in_table && NF == 0 { exit }
        in_table && $1 !~ /^[0-9]+$/ { exit }
    ' | sort -n -u
)

if [ "${#controller_ids[@]}" -eq 0 ]; then
    fail "no controllers parsed from dpraid show (need header 'CONTROLLER MODEL' + ID rows)"
    echo "[${NODE_IP}] hint: expected table like:" >&2
    echo "[${NODE_IP}]   ID CONTROLLER MODEL ... STAT ..." >&2
    echo "[${NODE_IP}]   0  DAPUSTOR ...        Optimal ..." >&2
    exit 1
fi

targets=()
for controller_id in "${controller_ids[@]}"; do
    targets+=("/c${controller_id}")
done
ok "found ${#controller_ids[@]} controller(s): ${targets[*]}"

banner "2/2 flash-clear --with-cache --force"
idx=0
for controller_id in "${controller_ids[@]}"; do
    idx=$((idx + 1))
    target="/c${controller_id}"
    echo "[${NODE_IP}] --- (${idx}/${#controller_ids[@]}) ${DPRAID_BIN} ${target} flash-clear --with-cache --force ---"
    set +e
    clear_output="$("${DPRAID_BIN}" "${target}" flash-clear --with-cache --force 2>&1)"
    clear_rc=$?
    set -e
    if [ -n "${clear_output}" ]; then
        printf '%s\n' "${clear_output}"
    fi
    if [ "${clear_rc}" -ne 0 ]; then
        fail "${DPRAID_BIN} ${target} flash-clear --with-cache --force failed (rc=${clear_rc})"
        echo "[${NODE_IP}] hint: controller ${target} missing or busy; re-check dpraid show IDs above" >&2
        exit 1
    fi
    ok "${target} flash-clear --with-cache --force succeeded"
done

banner "CSD flash+cache clear DONE"
ok "cleared controller(s): ${targets[*]}"
echo ""
