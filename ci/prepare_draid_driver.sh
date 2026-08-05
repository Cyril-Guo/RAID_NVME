#!/bin/bash
set -euo pipefail

: "${NODE_IP:?NODE_IP is required}"
: "${TARGET_USER:?TARGET_USER is required}"
: "${REMOTE_DIR:?REMOTE_DIR is required}"
: "${BUILD_NUMBER:?BUILD_NUMBER is required}"

SSH_OPTS=${SSH_OPTS:-}

host_ssh() {
    ssh ${SSH_OPTS} "${TARGET_USER}@${NODE_IP}" "$@"
}

host_scp() {
    scp ${SSH_OPTS} "$@"
}

reload_remote_module() {
    host_ssh "REMOTE_DIR='${REMOTE_DIR}' bash -s" <<'REMOTE_RELOAD'
set -euo pipefail
cd "${REMOTE_DIR}/kernel_driver/drivers/draid"
test -f ./draid.ko
module_name=$(modinfo -F name ./draid.ko 2>/dev/null || true)
module_name=${module_name:-draid}
echo "draid.ko module name: ${module_name}"
for candidate in "${module_name}" draid; do
    if [ -n "${candidate}" ] && grep -q "^${candidate} " /proc/modules; then
        rmmod "${candidate}" || modprobe -r "${candidate}"
    fi
done
for candidate in "${module_name}" draid; do
    if [ -n "${candidate}" ] && grep -q "^${candidate} " /proc/modules; then
        echo "kernel module ${candidate} is still loaded after remove attempt" >&2
        grep -i draid /proc/modules >&2 || true
        exit 1
    fi
done
sync || true
echo 3 >/proc/sys/vm/drop_caches 2>/dev/null || true
if ! insmod ./draid.ko; then
    sync || true
    echo 3 >/proc/sys/vm/drop_caches 2>/dev/null || true
    sleep 2
fi
if ! grep -q "^${module_name} " /proc/modules && ! insmod ./draid.ko; then
    echo "insmod ./draid.ko failed. Current related modules:" >&2
    grep -i draid /proc/modules >&2 || true
    echo "memory status after insmod failure:" >&2
    free -h >&2 || true
    grep -E '^(MemTotal|MemFree|MemAvailable|Buffers|Cached|SwapTotal|SwapFree|VmallocTotal|VmallocUsed|VmallocChunk):' /proc/meminfo >&2 || true
    echo "dmesg tail after insmod failure:" >&2
    dmesg | tail -n 160 >&2 || true
    exit 1
fi
grep -q "^${module_name} " /proc/modules

DRAID_READY_MAX_ATTEMPTS=${DRAID_READY_MAX_ATTEMPTS:-120}
DRAID_READY_RETRY_SECONDS=${DRAID_READY_RETRY_SECONDS:-2}

parse_controller_states() {
    awk '
        $1 ~ /^[0-9]+$/ {
            state = "unknown"
            for (i = 2; i <= NF; i++) {
                value = tolower($i)
                if (value == "online") {
                    state = "online"
                    break
                }
                if (value == "offline" || value == "offl") {
                    state = "offline"
                    break
                }
            }
            print $1, state
        }
    '
}

wait_for_draid_initialization() {
    attempt=1
    while [ "${attempt}" -le "${DRAID_READY_MAX_ATTEMPTS}" ]; do
        if DRAID_SHOW_OUTPUT=$(dpraid show 2>&1); then
            DRAID_CONTROLLER_STATES=$(printf '%s\n' "${DRAID_SHOW_OUTPUT}" | parse_controller_states)
            controller_count=$(printf '%s\n' "${DRAID_CONTROLLER_STATES}" | awk 'NF == 2 { count++ } END { print count + 0 }')
            unknown_count=$(printf '%s\n' "${DRAID_CONTROLLER_STATES}" | awk '$2 == "unknown" { count++ } END { print count + 0 }')
            if [ "${controller_count}" -gt 0 ] && [ "${unknown_count}" -eq 0 ]; then
                printf '%s\n' "${DRAID_SHOW_OUTPUT}"
                return 0
            fi
        fi
        echo "Waiting for draid controller initialization (${attempt}/${DRAID_READY_MAX_ATTEMPTS})..."
        sleep "${DRAID_READY_RETRY_SECONDS}"
        attempt=$((attempt + 1))
    done

    echo "draid controllers did not finish initialization in time. Last dpraid show output:" >&2
    printf '%s\n' "${DRAID_SHOW_OUTPUT:-<no output>}" >&2
    return 1
}

wait_for_all_draid_controllers_online() {
    expected_ids="$1"
    expected_count=$(printf '%s\n' "${expected_ids}" | awk 'NF == 1 { count++ } END { print count + 0 }')
    attempt=1

    while [ "${attempt}" -le "${DRAID_READY_MAX_ATTEMPTS}" ]; do
        if DRAID_SHOW_OUTPUT=$(dpraid show 2>&1); then
            DRAID_CONTROLLER_STATES=$(printf '%s\n' "${DRAID_SHOW_OUTPUT}" | parse_controller_states)
            current_count=$(printf '%s\n' "${DRAID_CONTROLLER_STATES}" | awk 'NF == 2 { count++ } END { print count + 0 }')
            non_online_count=$(printf '%s\n' "${DRAID_CONTROLLER_STATES}" | awk '$2 != "online" { count++ } END { print count + 0 }')
            missing_count=0
            for controller_id in ${expected_ids}; do
                if ! printf '%s\n' "${DRAID_CONTROLLER_STATES}" | awk -v id="${controller_id}" '$1 == id && $2 == "online" { found = 1 } END { exit !found }'; then
                    missing_count=$((missing_count + 1))
                fi
            done

            if [ "${expected_count}" -gt 0 ] &&
               [ "${current_count}" -eq "${expected_count}" ] &&
               [ "${non_online_count}" -eq 0 ] &&
               [ "${missing_count}" -eq 0 ]; then
                echo "All draid controllers are Online:"
                printf '%s\n' "${DRAID_SHOW_OUTPUT}"
                return 0
            fi
        fi
        echo "Waiting for all draid controllers to become Online (${attempt}/${DRAID_READY_MAX_ATTEMPTS})..."
        sleep "${DRAID_READY_RETRY_SECONDS}"
        attempt=$((attempt + 1))
    done

    echo "Not all draid controllers became Online in time. Last dpraid show output:" >&2
    printf '%s\n' "${DRAID_SHOW_OUTPUT:-<no output>}" >&2
    return 1
}

# Controller state check/reset is intentionally disabled. Loading draid no longer
# runs `dpraid show`, `reset-and-online`, or waits for all controllers to become Online.
# command -v dpraid >/dev/null 2>&1 || {
#     echo "dpraid is required to verify draid controller state" >&2
#     exit 1
# }
#
# wait_for_draid_initialization
# expected_controller_ids=$(printf '%s\n' "${DRAID_CONTROLLER_STATES}" | awk '{ print $1 }')
# offline_controller_ids=$(printf '%s\n' "${DRAID_CONTROLLER_STATES}" | awk '$2 == "offline" { print $1 }')
#
# for controller_id in ${offline_controller_ids}; do
#     echo "Controller ${controller_id} is Offline; run reset-and-online."
#     dpraid "/c${controller_id}" reset-and-online --force
# done
#
# wait_for_all_draid_controllers_online "${expected_controller_ids}"
REMOTE_RELOAD
}

install_driver_build_deps() {
    host_ssh 'bash -s' <<'REMOTE_DEPS'
set -euo pipefail
need_driver_deps=0
for tool in make gcc insmod modinfo; do
    command -v "${tool}" >/dev/null 2>&1 || need_driver_deps=1
done
[ -e "/lib/modules/$(uname -r)/build" ] || need_driver_deps=1
if [ "${need_driver_deps}" = "1" ]; then
    if command -v apt-get >/dev/null 2>&1; then
        export DEBIAN_FRONTEND=noninteractive
        apt_retry() {
            for attempt in 1 2 3; do
                "$@" && return 0
                echo "apt command failed, retry ${attempt}/3: $*" >&2
                sleep $((attempt * 10))
            done
            "$@"
        }
        apt_retry apt-get -o DPkg::Lock::Timeout=600 update
        apt_retry apt-get -o DPkg::Lock::Timeout=600 install -y build-essential "linux-headers-$(uname -r)" kmod
    elif command -v dnf >/dev/null 2>&1; then
        dnf install -y make gcc kernel-devel kmod
    elif command -v yum >/dev/null 2>&1; then
        yum install -y make gcc kernel-devel kmod
    fi
fi
REMOTE_DEPS
}

install_driver_build_deps
host_ssh "REMOTE_DIR='${REMOTE_DIR}' bash -s" <<'REMOTE_BUILD'
set -euo pipefail
cd "${REMOTE_DIR}/kernel_driver/drivers/draid"
make
test -f ./draid.ko
REMOTE_BUILD
reload_remote_module
