#!/usr/bin/env bash
set -euo pipefail

: "${NODE_IP:?NODE_IP is required}"
: "${TARGET_USER:?TARGET_USER is required}"
: "${SSH_OPTS:?SSH_OPTS is required}"
: "${BUILD_NUMBER:?BUILD_NUMBER is required}"
: "${DPRAID_SOURCE:?DPRAID_SOURCE is required}"
: "${TEST_IDLE_TIMEOUT_MINUTES:?TEST_IDLE_TIMEOUT_MINUTES is required}"

CONTROL_STEP_TIMEOUT_MINUTES=${CONTROL_STEP_TIMEOUT_MINUTES:-15}
host_remote_dir="/root/Cyril/Jenkins/jenkins_nvme_${BUILD_NUMBER}_physical"
host_log="environment_prepare_${NODE_IP}_physical.log"
host_ssh="ssh ${SSH_OPTS} ${TARGET_USER}@${NODE_IP}"
host_scp="scp ${SSH_OPTS}"
export NODE_IP TARGET_USER SSH_OPTS BUILD_NUMBER DPRAID_SOURCE host_remote_dir host_ssh host_scp

printf '[%s] Physical Environment_Prepare started after QEMU VM test\n' "${NODE_IP}" > "${host_log}"

fail_prepare() {
    printf '%s\n' 'ENVIRONMENT_PREPARE_STATUS=failed' >> "${host_log}"
    echo "[${NODE_IP}] ERROR: $*"
    exit 1
}

run_control_step() {
    local label="$1"
    shift

    echo "[${NODE_IP}] ${label}"
    set +e
    timeout --kill-after=60s "${CONTROL_STEP_TIMEOUT_MINUTES}m" "$@" 2>&1 | tee -a "${host_log}"
    local step_status=${PIPESTATUS[0]}
    set -e

    if [ "${step_status}" -eq 124 ] || [ "${step_status}" -eq 137 ]; then
        fail_prepare "${label} timed out after ${CONTROL_STEP_TIMEOUT_MINUTES} minutes"
    fi
    if [ "${step_status}" -ne 0 ]; then
        fail_prepare "${label} failed"
    fi
}

echo "[${NODE_IP}] stop QEMU VM and return NVMe devices to physical host"
chmod +x ci/qemu_vfio_cleanup.sh
set +e
timeout --kill-after=60s "${CONTROL_STEP_TIMEOUT_MINUTES}m" env \
    NODE_IP="${NODE_IP}" TARGET_USER="${TARGET_USER}" SSH_OPTS="${SSH_OPTS}" \
    QEMU_VM_PASSWORD="${QEMU_VM_PASSWORD:-}" QEMU_VM_SSH_PORT="${QEMU_VM_SSH_PORT:-2233}" \
    QEMU_VM_WORKDIR="${QEMU_VM_WORKDIR:-/root/Cyril/qemu}" QEMU_VFIO_BIND_SCRIPT="${QEMU_VFIO_BIND_SCRIPT:-./vfio-bind.sh}" \
    BUILD_NUMBER="${BUILD_NUMBER}" CLEANUP_REASON='stop QEMU VM and return NVMe devices to physical host' \
    POWER_OFF_QEMU=1 ci/qemu_vfio_cleanup.sh 2>&1 | tee -a "${host_log}"
cleanup_status=${PIPESTATUS[0]}
set -e
if [ "${cleanup_status}" -eq 124 ] || [ "${cleanup_status}" -eq 137 ]; then
    fail_prepare "returning NVMe devices to physical host timed out after ${CONTROL_STEP_TIMEOUT_MINUTES} minutes"
fi
if [ "${cleanup_status}" -ne 0 ]; then
    fail_prepare "returning NVMe devices to physical host failed"
fi

run_control_step "deploy workspace for physical host test" bash -c '
    ${host_ssh} "rm -rf ${host_remote_dir} && mkdir -p ${host_remote_dir}"
    chmod +x ci/deploy_workspace.sh
    NODE_IP="${NODE_IP}" TARGET_USER="${TARGET_USER}" REMOTE_DIR="${host_remote_dir}" \
        REMOTE_SSH_COMMAND="${host_ssh}" ci/deploy_workspace.sh
'

run_control_step "install latest dpraid on physical host" bash -c '
    chmod +x ci/install_dpraid_remote.sh
    NODE_IP="${NODE_IP}" TARGET_USER="${TARGET_USER}" SSH_OPTS="${SSH_OPTS}" DPRAID_SOURCE="${DPRAID_SOURCE}" \
        BUILD_NUMBER="${BUILD_NUMBER}" TMP_SUFFIX=_physical REMOTE_SSH_COMMAND="${host_ssh}" \
        REMOTE_SCP_COMMAND="${host_scp}" ci/install_dpraid_remote.sh
'

run_control_step "build and reload draid kernel driver on physical host" bash -c '
    chmod +x ci/prepare_draid_driver.sh
    NODE_IP="${NODE_IP}" TARGET_USER="${TARGET_USER}" SSH_OPTS="${SSH_OPTS}" REMOTE_DIR="${host_remote_dir}" \
        BUILD_NUMBER="${BUILD_NUMBER}" QEMU_VM_TARGET=0 ci/prepare_draid_driver.sh
'

# Clear leftover RAID objects after dpraid/draid are ready, before metadata/tests.
run_control_step "restore RAID state before physical host test" bash -c '
    ${host_ssh} "cd ${host_remote_dir} && chmod +x ci/restore_physical_raid_state.sh && NODE_IP=${NODE_IP} ci/restore_physical_raid_state.sh"
'

run_control_step "install python dependencies on physical host" bash -c '
    ${host_ssh} "cd ${host_remote_dir} && chmod +x ci/install_test_dependencies.sh && QEMU_VM_TARGET=0 ci/install_test_dependencies.sh"
'
printf '%s\n' 'ENVIRONMENT_PREPARE_STATUS=passed' >> "${host_log}"

run_control_step "collect physical host environment metadata" bash -c '
    ${host_ssh} "cd ${host_remote_dir} && chmod +x ci/collect_environment_metadata.sh && NODE_IP=${NODE_IP} REMOTE_DIR=${host_remote_dir} PREFIX=Node_${NODE_IP}_Physical SUFFIX=_physical ci/collect_environment_metadata.sh"
'

chmod +x ci/run_remote_test_and_collect.sh
NODE_IP="${NODE_IP}" TARGET_USER="${TARGET_USER}" REMOTE_DIR="${host_remote_dir}" \
    REMOTE_SSH_COMMAND="${host_ssh}" REMOTE_SCP_COMMAND="${host_scp}" \
    TEST_IDLE_TIMEOUT_MINUTES="${TEST_IDLE_TIMEOUT_MINUTES}" QEMU_VM_TARGET=0 \
    ALLOW_DESTRUCTIVE_FIO="${ALLOW_DESTRUCTIVE_FIO:-YES}" REPORT_SUFFIX='_physical' LOG_SUFFIX='_physical' \
    TEST_LABEL='physical host nvme_raid_test.py' ci/run_remote_test_and_collect.sh
