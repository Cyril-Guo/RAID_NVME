from pathlib import Path


def pipeline_sources():
    paths = [
        Path("Jenkinsfile"),
        *sorted(Path("powercycle").glob("*.sh")),
        *sorted(Path("powercycle").glob("*.py")),
        *sorted(Path("powercycle").glob("*.groovy")),
    ]
    return "\n".join(path.read_text(encoding="utf-8") for path in paths)


def test_apt_get_waits_for_dpkg_lock():
    source = pipeline_sources()

    assert source.count("DPkg::Lock::Timeout=600") >= 4
    assert "apt-get -o DPkg::Lock::Timeout=600 update" in source
    assert "apt-get -o DPkg::Lock::Timeout=600 install -y build-essential" in source
    assert "apt_retry apt-get -o DPkg::Lock::Timeout=600 install -y \\\n            python3-pip python3-pytest" in source


def test_debug_no_feishu_only_skips_notification():
    source = pipeline_sources()

    assert "name: 'DEBUG_NO_FEISHU'" in source
    assert "DEBUG_NO_FEISHU=true, skip Feishu notification." in source
    assert "python3 powercycle/build_feishu_payload.py" in source
    assert "python3 powercycle/extract_failure_summary.py --output failure_summary.txt" in source
    assert "feishu_payload.json" in source
    assert "def buildResult = currentBuild.currentResult ?: currentBuild.result ?: 'UNKNOWN'" in source
    assert '"BUILD_RESULT=${buildResult}"' in source
    assert '"REPORT_KIND=${reportKind}"' in source
    assert '"JOB_NAME=${env.JOB_NAME}"' in source
    assert '"BUILD_NUMBER=${env.BUILD_NUMBER}"' in source
    assert '"BUILD_URL=${env.BUILD_URL}"' in source
    assert "Feishu notification will use a fallback infra count" in source


def test_feishu_webhook_uses_jenkins_credential():
    source = Path("Jenkinsfile").read_text(encoding="utf-8")

    assert "FEISHU_WEBHOOK = credentials('feishu-webhook')" in source
    assert "https://open.feishu.cn/open-apis/bot/v2/hook/" not in source


def test_feishu_skips_empty_reports_when_no_reportable_result_exists():
    source = Path("Jenkinsfile").read_text(encoding="utf-8")

    assert "TEST_EXECUTION_ATTEMPTED = 'false'" in source
    assert "env.TEST_EXECUTION_ATTEMPTED = 'true'" in source
    assert "def testAttempted = (env.TEST_EXECUTION_ATTEMPTED == 'true')" in source
    assert "if (total == 0 && !hasFailureSummary)" in source
    assert "Skip Feishu notification: no reportable test or environment prepare result was generated in this build." in source
    assert "fileExists('feishu_payload.json')" in source
    assert "Skip Feishu notification: feishu_payload.json was not generated." in source
    assert "hasEnvironmentPrepareFailure" not in source


def test_failure_logs_are_added_to_allure_and_feishu_report():
    source = pipeline_sources()
    jenkinsfile = Path("Jenkinsfile").read_text(encoding="utf-8")

    assert "TEST_EXECUTION_STATUS=failed" in source
    assert "TEST_EXECUTION_EXIT_CODE=${test_rc}" in source
    assert "python3 powercycle/collect_console_output.py" in source
    assert "jenkins_console.log" in source
    assert "终端输出" in Path("powercycle/junit_to_allure.py").read_text(encoding="utf-8")
    assert "write_failed_execution_results" in source
    assert "python3 powercycle/extract_failure_summary.py --output failure_summary.txt" in jenkinsfile
    assert "failure_summary.txt" in jenkinsfile
    feishu = Path("powercycle/build_feishu_payload.py").read_text(encoding="utf-8")
    assert "查看MR" in feishu
    assert "详细日志" not in feishu
    assert "失败摘要" not in feishu
    assert "summary_indicates_hard_failure" in feishu
    assert "fio command failed" not in Path("powercycle/build_feishu_payload.py").read_text(encoding="utf-8").split("_HARD_SUMMARY_MARKERS", 1)[1].split(")", 1)[0]
    assert "报告类型" not in feishu
    assert "Hard failure summary detected; override BUILD_RESULT" in jenkinsfile
    assert "FIO Failure Detail" in Path("powercycle/junit_to_allure.py").read_text(encoding="utf-8")
    assert "FIO 任务摘要" in Path("test_items/fio_allure.py").read_text(encoding="utf-8")
    assert "complete local execution logs" in Path("powercycle/collect_console_output.py").read_text(encoding="utf-8")


def test_manual_mr_iid_reruns_merge_request():
    source = pipeline_sources()

    assert "name: 'MANUAL_MR_IID'" in source
    assert "Takes priority over MANUAL_KERNEL_DRIVER_REF" in source
    assert "MANUAL_MR_IID must be a numeric GitLab merge request IID" in source
    assert "merge_requests/${manualMrIid}" in source
    assert "kernel_driver_manual_mr.properties" in source
    assert "state.triggerSource = 'Manual MR Build'" in source
    assert "ignore MANUAL_KERNEL_DRIVER_REF=${manualKernelDriverRef}" in source
    assert "Manual build requested. Run tests on kernel_driver/${state.kernelDriverRef}." in source


def test_manual_build_can_select_kernel_driver_branch():
    source = pipeline_sources()

    assert "name: 'MANUAL_KERNEL_DRIVER_REF'" in source
    assert "def manualKernelDriverRef = (params.MANUAL_KERNEL_DRIVER_REF ?: '').trim()" in source
    assert "MANUAL_KERNEL_DRIVER_REF is not a safe branch name" in source
    assert "kernelDriverRef = manualKernelDriverRef" in source or "state.kernelDriverRef = manualKernelDriverRef" in source
    assert "state.triggerSource = 'Manual Branch Build'" in source
    assert "state.kernelDriverRef = env.KERNEL_DRIVER_BRANCH" in source
    assert "state.triggerSource = 'Manual Build'" in source


def test_target_hang_times_out_and_keeps_pipeline_control():
    source = pipeline_sources()
    fio_all = Path("IO_Stress/Fio_All.sh").read_text(encoding="utf-8")
    assert '-i restore' in fio_all or "RESTORE" in fio_all
    assert "only supports -i restore" in fio_all
    assert "fio_cycle" not in fio_all
    assert 'exit "${test_rc}"' in source


def test_manual_abort_is_not_converted_to_failure_or_feishu_notification():
    source = pipeline_sources()

    assert "powercycle/build_status.py --manual-abort jenkins_console.log" in source
    assert "isManualInterruption" in source
    assert "endsWith('UserInterruption')" in source
    assert "throw e" in source
    assert "currentBuild.currentResult == 'ABORTED'" in source
    assert "Manual abort detected without real test failures" in source
    assert "keep ABORTED and skip Feishu notification" in source


def test_report_publication_failures_do_not_skip_notification_finalization():
    source = Path("Jenkinsfile").read_text(encoding="utf-8")

    assert "def publicationErrors = []" in source
    assert "JUnit publication failed" in source
    assert "Allure publication failed" in source
    assert "Artifact archive failed" in source
    assert "Continue to Feishu finalization" in source


def test_environment_prepare_hang_times_out_after_15_minutes():
    source = pipeline_sources()
    jenkinsfile = Path("Jenkinsfile").read_text(encoding="utf-8")
    prepare = Path("powercycle/jenkins_prepare.groovy").read_text(encoding="utf-8")

    assert "load 'powercycle/jenkins_prepare.groovy'" in jenkinsfile
    assert "preparePhysicalIoDriver" in jenkinsfile
    assert "def preparePhysicalIoDriver" in prepare

    assert "def runTimedEnvironmentStep(" in source
    assert "timeout(time: timeoutMinutes.toInteger(), unit: 'MINUTES')" in source
    for label in [
        "deploy workspace",
        "install python dependencies",
        "collect environment metadata",
    ]:
        assert f"runTimedEnvironmentStep(ip, '{label}'" in jenkinsfile
    # Shared env prepare must not refresh draid/dpraid for every case.
    assert "runTimedEnvironmentStep(ip, 'install latest dpraid'" not in jenkinsfile
    assert "runTimedEnvironmentStep(ip, 'build and reload draid kernel driver'" not in jenkinsfile
    assert "needsPhysicalIoDriverPrep" in jenkinsfile
    assert "prepare_env.sh" in jenkinsfile
    assert "env_prepare" in jenkinsfile
    assert "artifacts/dpraid" in jenkinsfile
    assert "clear dirty CSD flash before loading draid" not in jenkinsfile
    assert "restore RAID state before test" not in jenkinsfile
    assert "powercycle/clear_8p_csd_flash.sh" not in jenkinsfile
    assert "powercycle/restore_physical_raid_state.sh" not in jenkinsfile
    assert "powercycle/wait_powercycle_completion.sh" in jenkinsfile
    assert "RAID_CLI_REPO" in source
    assert "RAID_CLI_COMMIT" in jenkinsfile


def test_test_idle_watchdog_tracks_non_system_disk_io_progress():
    source = Path("powercycle/io_progress_signature.sh").read_text(encoding="utf-8")

    assert "lsblk -nr -o NAME,PKNAME,MOUNTPOINT" in source
    assert '"/sys/block/${dev}/stat"' in source
    assert "loop*|ram*|sr*|fd*|md*|dm-*|zram*" in source
    assert 'if is_protected "${dev}"; then' in source
    assert 'awk -v dev="${dev}"' in source
    assert "active_fio_devices" in source
    assert "/^dp[0-9]+-vd[0-9]+$/" in source


def test_ci_is_manual_only_without_cron_or_auto_mr_trigger():
    jenkinsfile = Path("Jenkinsfile").read_text(encoding="utf-8")
    source = pipeline_sources()

    assert "cron(" not in jenkinsfile
    assert "triggers {" not in jenkinsfile
    assert "name: 'SIMULATE_AUTO_MR_TRIGGER'" not in jenkinsfile
    assert "automaticMrTriggered" not in source
    assert "useQemuVmTarget" not in source
    assert "triggerSource = 'kernel_driver Merge Request'" not in source
    assert "merge_requests?state=opened" not in source
    assert "kernel_driver_open_mrs" not in source
    assert "existingMrShaChanged || newlyCreatedMr" not in source
    assert "CI is manual-only" in source
    assert "Manual Build" in source


def test_draid_module_reload_retries_and_reports_memory_on_insmod_failure():
    source = pipeline_sources()

    assert "echo 3 >/proc/sys/vm/drop_caches" in source
    assert "memory status after insmod failure" in source
    assert "dmesg tail after insmod failure" in source
    assert "VmallocTotal" in source


def test_draid_module_unload_and_load_are_disabled():
    source = Path("powercycle/prepare_draid_driver.sh").read_text(encoding="utf-8")
    stripped_lines = [line.strip() for line in source.splitlines() if line.strip()]

    assert "Module unload/load (rmmod/insmod) is temporarily disabled for CI" in source
    assert "skip draid module unload/load (temporarily disabled)" in source
    assert "make -j 8 ACCEL_CDEV=y" in source
    assert "# reload_remote_module" in stripped_lines
    assert "reload_remote_module" not in stripped_lines


def test_draid_controller_state_check_and_reset_are_disabled():
    source = Path("powercycle/prepare_draid_driver.sh").read_text(encoding="utf-8")
    active_lines = {
        line.strip()
        for line in source.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert "Controller state check/reset is intentionally disabled" in source
    assert "wait_for_draid_initialization" not in active_lines
    assert 'dpraid "/c${controller_id}" reset-and-online --force' not in active_lines
    assert 'wait_for_all_draid_controllers_online "${expected_controller_ids}"' not in active_lines


def test_physical_host_installs_full_test_tool_set():
    source = pipeline_sources()

    assert "need_test_deps=0" in source
    assert "fix_ubuntu_package_architectures" in source
    assert "ensure_ubuntu_china_mirrors" in source
    assert "dpkg --print-architecture" in source
    assert 'if [ "${architecture}" = "amd64" ]; then' in source
    assert "99raid-nvme-native-architecture" in source
    assert 'APT::Architecture "amd64";' in source
    assert 'APT::Architectures { "amd64"; };' in source
    assert "dpkg --remove-architecture" not in source
    assert "keep registered foreign architectures unchanged" in source
    assert "arm64|armhf" in source
    assert "mirrors.aliyun.com" in source
    assert "ubuntu-ports" in source
    assert "archive\\.ubuntu\\.com" in source or "archive.ubuntu.com" in source
    assert "apt_retry apt-get -o DPkg::Lock::Timeout=600 update" in source
    assert "fio nvme-cli pciutils util-linux smartmontools sdparm" in source
    assert "sysstat gawk nmap bc psmisc numactl lsscsi unzip" in source
    assert "xfsprogs parted make gcc g++" in source
    assert "build-essential" in source
    assert "linux-headers-$(uname -r)" in source
    assert "kmod" in source
    assert "ripgrep" in source
    assert "python3-pip python3-pytest python-is-python3" in source
    assert "for tool in fio nvme lspci findmnt lsblk rg make gcc insmod modinfo gcore; do" in source
    assert "Missing required test/driver-build tools after auto install" in source


def test_run_tests_uses_password_host_ssh_without_qemu_ports():
    source = Path("Jenkinsfile").read_text(encoding="utf-8")

    assert "def targetSsh = hostSshCmd(ip)" in source
    assert "def targetScp = hostScpCmd()" in source
    assert "sshpass -e ssh" in source
    assert "SSHPASS = " in Path("Jenkinsfile").read_text(encoding="utf-8")
    assert "SSHPASS='${env.TARGET_PASSWORD}'" not in source
    assert "${targetSsh} 'rm -rf ${remoteDir} && mkdir -p ${remoteDir}'" in source
    assert "find /root/Cyril/Jenkins -maxdepth 1 -type d -name" not in source
    assert "jenkins_nvme_*" not in source
    assert "def remoteWorkspaceRoot(" in source
    assert "/root/Cyril/Jenkins/${job}/${branch}/${prefix}-${env.BUILD_NUMBER}" in source
    assert "QEMU_VM_SSH_PORT" not in source


def test_physical_host_ssh_uses_password_with_default_and_override():
    jenkinsfile = Path("Jenkinsfile").read_text(encoding="utf-8")
    source = pipeline_sources()

    assert "name: 'TARGET_PASSWORD'" in jenkinsfile
    assert "defaultValue: ''" in jenkinsfile
    assert "TARGET_PASSWORD is required" in jenkinsfile
    assert "SSHPASS = " in jenkinsfile
    assert 'return "sshpass -e ssh' in jenkinsfile
    assert "SSHPASS='${env.TARGET_PASSWORD}' sshpass" not in jenkinsfile
    assert "sshpass -e ssh" in source
    assert "sshpass -e scp" in source



def test_draid_driver_and_test_dependency_steps_target_physical_host_only():
    source = Path("Jenkinsfile").read_text(encoding="utf-8")

    assert "QEMU_VM_TARGET" not in source
    assert "powercycle/install_test_dependencies.sh" in source
    assert "needsPhysicalIoDriverPrep" in source
    assert "env_prepare" in source


def test_physical_io_driver_pull_and_prep_only_for_env_prepare():
    jenkinsfile = Path("Jenkinsfile").read_text(encoding="utf-8")
    source = pipeline_sources()

    assert "read_enabled_selection" in jenkinsfile
    assert "Skip raid_cli sync and kernel_driver checkout" in source
    assert "skip shared install_dpraid/prepare_draid" in jenkinsfile
    assert "needsEnvPrepare" in source
    assert "name.endsWith('_env_prepare')" in source
    assert "name == 'env_prepare'" in source
    assert "when { expression { return !params.RESTORE && shouldRunTests && needsPhysicalIoDriverPrep } }" in jenkinsfile


def test_run_remote_test_reports_error_without_qemu_scene_keep_message():
    source = Path("Jenkinsfile").read_text(encoding="utf-8")

    assert "keep VM/vfio devices for failure analysis" not in source
    assert "Next triggered run will reclaim them in pre-test cleanup" not in source
    assert 'error "[${ip}] nvme_raid_test.py or report collection failed with exit code ${testStatus}"' in source
    # Fail-fast pytest errors must surface before powercycle wait failures.
    test_error_idx = source.index(
        'error "[${ip}] nvme_raid_test.py or report collection failed with exit code ${testStatus}"'
    )
    wait_error_idx = source.index(
        'error "[${ip}] powercycle completion wait failed with exit code ${powercycleWaitStatus}"'
    )
    assert test_error_idx < wait_error_idx


def test_environment_prepare_uses_errexit_and_marks_passed_after_metadata():
    source = Path("Jenkinsfile").read_text(encoding="utf-8")

    assert "set -euo pipefail" in source
    passed_idx = source.index("ENVIRONMENT_PREPARE_STATUS=passed")
    metadata_idx = source.index("collect environment metadata")
    assert metadata_idx < passed_idx


def test_report_metrics_parse_is_tolerant_of_unexpected_output():
    source = Path("Jenkinsfile").read_text(encoding="utf-8")

    assert "unexpected report_metrics output" in source
    assert "failed to parse report_metrics output" in source


def test_junit_glob_only_collects_node_level_reports():
    source = Path("Jenkinsfile").read_text(encoding="utf-8")

    assert "junit testResults: 'report_*.*.*.*.xml', allowEmptyResults: true" in source
    assert "report_*_physical.xml" not in source




def test_jenkins_sets_sshpass_env_without_embedding_password_in_helper():
    # timeout wiring checked in test_jenkins_wires_powercycle_completion_timeout
    jenkinsfile = Path("Jenkinsfile").read_text(encoding="utf-8")
    assert "SSHPASS = " in jenkinsfile
    assert 'return "sshpass -e ssh' in jenkinsfile
    assert "SSHPASS='${env.TARGET_PASSWORD}' sshpass" not in jenkinsfile
    assert "POWER_CYCLE_COMPLETION_TIMEOUT_MINUTES = '4000'" in jenkinsfile
    assert "POWER_CYCLE_COMPLETION_TIMEOUT_MINUTES='${env.POWER_CYCLE_COMPLETION_TIMEOUT_MINUTES}'" in jenkinsfile
