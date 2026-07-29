from pathlib import Path


def pipeline_sources():
    paths = [
        Path("Jenkinsfile"),
        *sorted(Path("ci").glob("*.sh")),
        *sorted(Path("ci").glob("*.py")),
    ]
    return "\n".join(path.read_text(encoding="utf-8") for path in paths)


def test_apt_get_waits_for_dpkg_lock():
    source = pipeline_sources()

    assert source.count("DPkg::Lock::Timeout=600") >= 4
    assert "apt-get -o DPkg::Lock::Timeout=600 update" in source
    assert "apt-get -o DPkg::Lock::Timeout=600 install -y build-essential" in source
    assert "apt_retry apt-get -o DPkg::Lock::Timeout=600 install -y python3-pip python3-pytest" in source


def test_debug_no_feishu_only_skips_notification():
    source = pipeline_sources()

    assert "name: 'DEBUG_NO_FEISHU'" in source
    assert "DEBUG_NO_FEISHU=true, skip Feishu notification." in source
    assert "python3 ci/build_feishu_payload.py" in source
    assert "feishu_payload.json" in source
    assert "def buildResult = currentBuild.currentResult ?: currentBuild.result ?: 'UNKNOWN'" in source
    assert '"BUILD_RESULT=${buildResult}"' in source


def test_feishu_webhook_uses_jenkins_credential():
    source = Path("Jenkinsfile").read_text(encoding="utf-8")

    assert "FEISHU_WEBHOOK = credentials('feishu-webhook')" in source
    assert "https://open.feishu.cn/open-apis/bot/v2/hook/" not in source


def test_feishu_skips_empty_reports_when_no_reportable_result_exists():
    source = Path("Jenkinsfile").read_text(encoding="utf-8")

    assert "TEST_EXECUTION_ATTEMPTED = 'false'" in source
    assert "env.TEST_EXECUTION_ATTEMPTED = 'true'" in source
    assert "def testAttempted = (env.TEST_EXECUTION_ATTEMPTED == 'true')" in source
    assert "if (total == 0)" in source
    assert "Skip Feishu notification: no reportable test or environment prepare result was generated in this build." in source
    assert "fileExists('feishu_payload.json')" in source
    assert "Skip Feishu notification: feishu_payload.json was not generated." in source
    assert "hasEnvironmentPrepareFailure" not in source


def test_failure_logs_are_added_to_allure_and_feishu_report():
    source = pipeline_sources()
    jenkinsfile = Path("Jenkinsfile").read_text(encoding="utf-8")

    assert "TEST_EXECUTION_STATUS=failed" in source
    assert "TEST_EXECUTION_EXIT_CODE=${test_rc}" in source
    assert "python3 ci/collect_console_output.py" in source
    assert "jenkins_console.log" in source
    assert "Jenkins Console Output" in source
    assert "write_failed_execution_results" in source
    assert "python3 ci/extract_failure_summary.py" not in jenkinsfile
    assert "failure_summary.txt" not in jenkinsfile


def test_manual_mr_iid_reruns_merge_request():
    source = Path("Jenkinsfile").read_text(encoding="utf-8")

    assert "name: 'MANUAL_MR_IID'" in source
    assert "MANUAL_MR_IID must be a numeric GitLab merge request IID" in source
    assert "merge_requests/${manualMrIid}" in source
    assert "kernel_driver_manual_mr.properties" in source
    assert "'Manual MR Build (Simulate Auto MR)' : 'Manual MR Build'" in source
    assert "Manual build requested. Run smoke tests on kernel_driver/${kernelDriverRef}." in source


def test_target_hang_times_out_and_keeps_pipeline_control():
    source = pipeline_sources()

    assert "TARGET_NODE_TIMEOUT_MINUTES" not in source
    assert "TEST_IDLE_TIMEOUT_MINUTES = '15'" in source
    assert "ENVIRONMENT_STEP_TIMEOUT_MINUTES = '15'" in source
    assert "ServerAliveInterval=30" in source
    assert "ServerAliveCountMax=3" in source
    assert "ConnectTimeout=15" in source
    assert "TEST_IDLE_TIMEOUT_MINUTES='${env.TEST_IDLE_TIMEOUT_MINUTES}'" in source
    assert ': "${TEST_IDLE_TIMEOUT_MINUTES:?TEST_IDLE_TIMEOUT_MINUTES is required}"' in source
    assert "ci/io_progress_signature.sh" in source
    assert "made no log or non-system disk IO progress for ${TEST_IDLE_TIMEOUT_MINUTES} minutes" in source
    assert "idle watchdog fired after ${TEST_IDLE_TIMEOUT_MINUTES} minutes without progress" in source
    assert 'exit "${test_rc}"' in source


def test_environment_prepare_hang_times_out_after_15_minutes():
    source = pipeline_sources()

    assert "def runTimedEnvironmentStep(" in source
    assert "timeout(time: env.ENVIRONMENT_STEP_TIMEOUT_MINUTES.toInteger(), unit: 'MINUTES')" in source
    assert "QEMU pre-test cleanup timed out after ${env.ENVIRONMENT_STEP_TIMEOUT_MINUTES} minutes" in source
    assert "QEMU VM startup timed out after ${env.ENVIRONMENT_STEP_TIMEOUT_MINUTES} minutes" in source
    for label in [
        "deploy workspace",
        "install latest dpraid",
        "build and reload draid kernel driver",
        "install python dependencies",
        "collect environment metadata",
    ]:
        assert f"runTimedEnvironmentStep(ip, '{label}'" in source
    assert "CONTROL_STEP_TIMEOUT_MINUTES=${CONTROL_STEP_TIMEOUT_MINUTES:-15}" in source
    assert "run_control_step()" in source
    assert 'timeout --kill-after=60s "${CONTROL_STEP_TIMEOUT_MINUTES}m" env' in source
    assert "returning NVMe devices to physical host timed out after ${CONTROL_STEP_TIMEOUT_MINUTES} minutes" in source
    for label in [
        "deploy workspace for physical host test",
        "install latest dpraid on physical host",
        "build and reload draid kernel driver on physical host",
        "install python dependencies on physical host",
        "collect physical host environment metadata",
        "restore physical host RAID state after physical host test",
    ]:
        assert f'run_control_step "{label}"' in source


def test_test_idle_watchdog_tracks_non_system_disk_io_progress():
    source = Path("ci/io_progress_signature.sh").read_text(encoding="utf-8")

    assert "lsblk -nr -o NAME,PKNAME,MOUNTPOINT" in source
    assert '"/sys/block/${dev}/stat"' in source
    assert "loop*|ram*|sr*|fd*|md*|dm-*|zram*" in source
    assert 'if is_protected "${dev}"; then' in source
    assert 'awk -v dev="${dev}"' in source


def test_automatic_mr_uses_qemu_vm_without_changing_manual_mr():
    source = pipeline_sources()

    assert "useQemuVmTarget = params.SIMULATE_AUTO_MR_TRIGGER" in source
    assert "useQemuVmTarget = true" in source
    assert "'Manual MR Build (Simulate Auto MR)' : 'Manual MR Build'" in source
    assert "triggerSource = 'kernel_driver Merge Request'" in source
    assert "QEMU_VM_SSH_PORT = '2233'" in source
    assert "QEMU_VM_SCP_PORT = '2233'" in source
    assert "QEMU_VM_WORKDIR = '/root/Cyril/qemu'" in source
    assert "QEMU_KERNEL_BUILD_DIR = '/root/Cyril/qemu/general_kernel'" in source
    assert "cd \"${QEMU_VM_WORKDIR}\"" in source
    assert "\"${QEMU_VM_START_SCRIPT}\"" in source
    assert "QEMU_VM_TARGET=${qemuEnv}" in source
    assert "sshpass is required on Jenkins server for QEMU VM login, and automatic install failed" in source


def test_automatic_mr_signature_only_tracks_code_sha():
    source = pipeline_sources()

    assert 'f"{mr.get(\'iid\')}:{mr.get(\'sha\')}"' in source
    assert 'f"{mr.get(\'iid\')}:{mr.get(\'updated_at\')}:{mr.get(\'sha\')}"' not in source
    assert 'parts.size() >= 3 ? "${parts[0]}:${parts[-1]}" : signature' in source
    assert "MR_CREATED_EPOCH_SIGNATURE" in source
    assert "existingMrShaChanged || newlyCreatedMr" in source
    assert "createdEpochByIid[iid]" in source
    assert "stat -c %Y '${markerPath}'" in source
    assert "kernel_driver MR marker bootstrap initialized" in source
    assert "Existing open merge requests are recorded as baseline, skip tests." in source


def test_draid_module_reload_retries_and_reports_memory_on_insmod_failure():
    source = pipeline_sources()

    assert "echo 3 >/proc/sys/vm/drop_caches" in source
    assert "memory status after insmod failure" in source
    assert "dmesg tail after insmod failure" in source
    assert "VmallocTotal" in source


def test_draid_controllers_are_online_before_tests_start():
    source = Path("ci/prepare_draid_driver.sh").read_text(encoding="utf-8")

    module_loaded = source.index('grep -q "^${module_name} " /proc/modules')
    show_controller_state = source.index("wait_for_draid_initialization", module_loaded)
    reset_offline_controller = source.index('dpraid "/c${controller_id}" reset-and-online --force')
    verify_all_online = source.index('wait_for_all_draid_controllers_online "${expected_controller_ids}"')

    assert module_loaded < show_controller_state < reset_offline_controller < verify_all_online
    assert "DRAID_READY_MAX_ATTEMPTS" in source
    assert '$2 == "offline"' in source
    assert '$2 != "online"' in source
    assert "Not all draid controllers became Online in time" in source


def test_qemu_vm_installs_sshpass_on_jenkins_server():
    source = pipeline_sources()

    assert "sshpass is missing on Jenkins server, try to install it automatically." in source
    assert "sudo apt-get -o DPkg::Lock::Timeout=600 install -y sshpass" in source
    assert "sudo dnf install -y sshpass" in source
    assert "sudo yum install -y sshpass" in source
    assert "sudo zypper install -y sshpass" in source


def test_qemu_vm_start_forces_clean_environment_before_start():
    source = pipeline_sources()

    assert "qemu vm already running" in source
    assert "pre-test cleanup: stop existing QEMU VM and return vfio devices to physical host" in source
    assert "QEMU pre-test cleanup failed with exit code" in source
    assert "QEMU VM is still running before fresh start; try to power it off" in source
    assert "QEMU VM is still running after pre-test cleanup; refuse to reuse stale VM" in source
    assert "force stop stale QEMU processes on host" in source
    assert "force stop stale QEMU process before fresh start" in source
    assert "QEMU VM is already running, skip vfio bind and ${QEMU_VM_START_SCRIPT}" not in source
    assert "dpraid_${BUILD_NUMBER}_host_prepare" in source
    assert "restore physical host RAID state before QEMU handoff" in source
    assert "\"${QEMU_VM_START_SCRIPT}\"" in source
    assert "QEMU VM SSH is ready" in source


def test_qemu_vm_deploy_cleans_previous_remote_workspaces():
    source = Path("Jenkinsfile").read_text(encoding="utf-8")

    assert "if [ '${qemuEnv}' = '1' ]; then" in source
    assert "find /root/Cyril/Jenkins -maxdepth 1 -type d -name" in source
    assert "jenkins_nvme_*" in source
    assert "-exec rm -rf {} +" in source
    assert "${targetSsh} 'rm -rf ${remoteDir} && mkdir -p ${remoteDir}'" in source


def test_qemu_vm_start_fails_fast_when_qemu_process_exits():
    source = pipeline_sources()

    assert "qemu-system-x86_64.*vm-serial.log" in source
    assert "QEMU process is not running after ${QEMU_VM_START_SCRIPT}; startup failed before SSH wait" in source
    assert "QEMU process exited before SSH became ready; stop waiting and fail startup" in source
    assert "QEMU startup failed, return vfio devices to physical host" in source
    assert "fallback unbind vfio NVMe PCI device back to host" in source


def test_automatic_mr_runs_qemu_then_physical_host():
    source = pipeline_sources()

    assert "automaticMrTriggered = true" in source
    assert "if (qemuVmForNode && automaticMrTriggered)" in source
    assert "Physical Environment_Prepare started after QEMU VM test" in source
    assert "QEMU_VM_TARGET=0" in source
    assert "REPORT_SUFFIX='_physical'" in source


def test_automatic_mr_moves_nvme_between_host_and_qemu():
    source = pipeline_sources()

    assert "QEMU_VFIO_BIND_SCRIPT = './vfio-bind.sh'" in source
    assert "VFIO_BIND_TIMEOUT_SECONDS=${VFIO_BIND_TIMEOUT_SECONDS:-30}" in source
    assert 'timeout --kill-after=5s "${VFIO_BIND_TIMEOUT_SECONDS}s"' in source
    assert "vfio ${action} timed out after ${VFIO_BIND_TIMEOUT_SECONDS}s" in source
    assert "bind NVMe PCI device to QEMU vfio" in source
    assert "skip invalid QEMU vfio device" in source
    assert '[ ! -e "/dev/vfio/${group}" ]' in source
    assert "no usable QEMU vfio NVMe devices after bind validation" in source
    assert "QEMU_ALLOWED_VFIO_FILE" in source
    assert "skip QEMU vfio device not in validated list" in source
    assert "skip QEMU vfio device without vfio node" in source
    assert "append auto detected QEMU vfio device" in source
    assert "skip auto QEMU vfio device without vfio node" in source
    assert 'patched_start_script=".jenkins_start_vm_${BUILD_NUMBER}.sh"' in source
    assert "*PASSTHROUGH_HOSTS block not found" in source
    assert "replace ${passthrough_var} in ${QEMU_VM_START_SCRIPT} with current validated BDF list" in source
    assert "^[[:space:]]*[A-Za-z_][A-Za-z0-9_]*PASSTHROUGH_HOSTS=\\(" in source
    assert "use auto detected QEMU passthrough hosts from ${allowed_file}" in source
    assert "use original script and rely on QEMU vfio wrapper filtering" in source
    assert ".jenkins_qemu_start_${BUILD_NUMBER}.log" in source
    assert "waiting for QEMU process" in source
    assert "return NVMe devices to physical host" in source
    assert "unbind NVMe PCI device back to host" in source
    assert "fallback unbind vfio NVMe PCI device back to host" in source
    assert ".jenkins_nvme_${BUILD_NUMBER}_vfio_devices" in source


def test_automatic_mr_restores_physical_host_raid_state_before_and_after_tests():
    source = pipeline_sources()

    assert "restore physical host RAID state before QEMU handoff" in source
    assert "restore physical host RAID state after physical host test" in source
    assert "unload draid module before QEMU handoff if loaded" in source
    assert "unload draid module before restoring physical RAID state if loaded" in source
    assert "dpraid /c0/vall show" in source
    assert "dpraid /c0/eall/sall show" in source
    assert 'dpraid "/c0/v${vd}" delete' in source
    assert 'dpraid "/c0/eall/s${slot}" delete' in source


def test_manual_debug_can_simulate_automatic_mr_trigger():
    source = Path("Jenkinsfile").read_text(encoding="utf-8")

    assert "name: 'SIMULATE_AUTO_MR_TRIGGER'" in source
    assert "automaticMrTriggered = params.SIMULATE_AUTO_MR_TRIGGER" in source
    assert "Manual MR Build (Simulate Auto MR)" in source
    assert "Manual Build (Simulate Auto MR)" in source
    assert "SIMULATE_AUTO_MR_TRIGGER=true, use QEMU VM target path for this manual build." in source
    assert "merge_requests/${manualMrIid}" in source


def test_qemu_vm_auto_installs_required_test_tools():
    source = pipeline_sources()

    assert 'if [ "$qemu_env" = "1" ]; then' in source
    assert "need_test_deps=0" in source
    assert "apt_retry apt-get -o DPkg::Lock::Timeout=600 update" in source
    assert "fio nvme-cli pciutils util-linux smartmontools sdparm" in source
    assert "sysstat gawk nmap bc psmisc numactl lsscsi unzip" in source
    assert "xfsprogs parted make gcc g++" in source
    assert "apt-get -o DPkg::Lock::Timeout=600 install -y python3-pip python3-pytest" in source
    assert "for tool in fio nvme lspci findmnt lsblk; do" in source
    assert "Missing required QEMU VM test tools after auto install" in source


def test_qemu_vm_builds_draid_against_qemu_host_kernel_tree():
    source = pipeline_sources()

    assert 'if [ "${QEMU_VM_TARGET}" = "1" ]; then' in source
    assert "QEMU kernel build dir not found: ${QEMU_KERNEL_BUILD_DIR}" in source
    assert "Local kernel_driver draid source not found: ${local_draid_src}" in source
    assert "test -d kernel_driver/drivers/draid && test -f kernel_driver/drivers/draid/Makefile" in source
    assert 'local_draid_src="kernel_driver/drivers/draid"' in source
    assert 'tar -czf "${local_archive}" -C "${local_draid_src}" .' in source
    assert 'host_scp "${local_archive}" "${TARGET_USER}@${NODE_IP}:${host_archive}"' in source
    assert 'tar -xzf "${host_archive}" -C "${host_build_dir}"' in source
    assert 'make -C "${QEMU_KERNEL_BUILD_DIR}" M="${host_build_dir}" modules' in source
    assert "mkdir -p '${REMOTE_DIR}/kernel_driver/drivers/draid'" in source
    assert 'target_scp "${local_module}"' in source


def test_qemu_vm_shell_variables_are_escaped_for_groovy():
    source = pipeline_sources()

    assert 'command -v "$tool"' in source
    assert 'missing_tools="${missing_tools} ${tool}"' in source
    assert 'after auto install:${missing_tools}' in source
