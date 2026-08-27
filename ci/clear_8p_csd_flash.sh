#!/usr/bin/env bash
set -euo pipefail

# Clear CSD flash+cache via dpraid on each controller reported by `dpraid show`.
# Example: one controller -> /c0; two controllers -> /c0 and /c1.

NODE_IP=${NODE_IP:-unknown}
DPRAID_BIN=${DPRAID_BIN:-dpraid}

if ! command -v "${DPRAID_BIN}" >/dev/null 2>&1 && [ ! -x "${DPRAID_BIN}" ]; then
    echo "[${NODE_IP}] ERROR: dpraid command not found" >&2
    exit 1
fi

echo "[${NODE_IP}] dpraid show (discover controllers for flash-clear)"
show_output="$("${DPRAID_BIN}" show 2>&1)" || {
    echo "[${NODE_IP}] ERROR: dpraid show failed" >&2
    printf '%s\n' "${show_output}" >&2
    exit 1
}
printf '%s\n' "${show_output}"

mapfile -t controller_ids < <(
    printf '%s\n' "${show_output}" | awk '$1 ~ /^[0-9]+$/ { print $1 }' | sort -n -u
)

if [ "${#controller_ids[@]}" -eq 0 ]; then
    echo "[${NODE_IP}] ERROR: no draid controllers found in dpraid show output" >&2
    exit 1
fi

echo "[${NODE_IP}] flash-clear controllers: ${controller_ids[*]}"
for controller_id in "${controller_ids[@]}"; do
    echo "[${NODE_IP}] ${DPRAID_BIN} /c${controller_id} flash-clear --with-cache --force"
    "${DPRAID_BIN}" "/c${controller_id}" flash-clear --with-cache --force
done

echo "[${NODE_IP}] CSD flash+cache clear finished for controller(s): ${controller_ids[*]}"
