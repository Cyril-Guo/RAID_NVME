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
    assert "apt_retry apt-get -o DPkg::Lock::Timeout=600 install -y \\\n            python3-pip python3-pytest" in source


def test_debug_no_feishu_only_skips_notification():
    source = pipeline_sources()

    assert "name: 'DEBUG_NO_FEISHU'" in source
    assert "DEBUG_NO_FEISHU=true, skip Feishu notification." in source
    assert "python3 ci/build_feishu_payload.py" in source
    assert "python3 ci/extract_failure_summary.py --output failure_summary.txt" in source
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
    assert "python3 ci/collect_console_output.py" in source
    assert "jenkins_console.log" in source
    assert "Jenkins Console Output" in source
    assert "write_failed_execution_results" in source
    assert "python3 ci/extract_failure_summary.py --output failure_summary.txt" in jenkinsfile
    assert "failure_summary.txt" in jenkinsfile
    feishu = Path("ci/build_feishu_payload.py").read_text(encoding="utf-8")
    assert "查看MR" in feishu
    assert "失败摘要" not in feishu
    assert "报告类型" not in feishu


def test_manual_mr_iid_reruns_merge_request():
    source = Path("Jenkinsfile").read_text(encoding="utf-8")

    assert "name: 'MANUAL_MR_IID'" in source
    assert "Takes priority over MANUAL_KERNEL_DRIVER_REF" in source
    assert "MANUAL_MR_IID must be a numeric GitLab merge request IID" in source
    assert "merge_requests/${manualMrIid}" in source
    assert "kernel_driver_manual_mr.properties" in source
    assert "triggerSource = 'Manual MR Build'" in source
    assert "ignore MANUAL_KERNEL_DRIVER_REF=${manualKernelDriverRef}" in source
    assert "Manual build requested. Run tests on kernel_driver/${kernelDriverRef}." in source


def test_manual_build_can_select_kernel_driver_branch():
    source = Path("Jenkinsfile").read_text(encoding="utf-8")

    assert "name: 'MANUAL_KERNEL_DRIVER_REF'" in source
    assert "def manualKernelDriverRef = (params.MANUAL_KERNEL_DRIVER_REF ?: '').trim()" in source
    assert "MANUAL_KERNEL_DRIVER_REF is not a safe branch name" in source
    assert "kernelDriverRef = manualKernelDriverRef" in source
    assert "triggerSource = 'Manual Branch Build'" in source
    assert "kernelDriverRef = env.KERNEL_DRIVER_BRANCH" in source
    assert "triggerSource = 'Manual Build'" in source


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
    assert "timeout(time: timeoutMinutes.toInteger(), unit: 'MINUTES')" in source
    for label in [
        "deploy workspace",
        "clear dirty CSD flash before loading draid",
        "install latest dpraid",
        "build and reload draid kernel driver",
        "restore RAID state before test",
        "install python dependencies",
        "collect environment metadata",
    ]:
        assert f"runTimedEnvironmentStep(ip, '{label}'" in source
    assert "ci/clear_8p_csd_flash.sh" in source
    assert "printf 'CLEAR\\n'" in Path("ci/clear_8p_csd_flash.sh").read_text(encoding="utf-8")
    assert "is_dirty_csd_size()" in Path("ci/clear_8p_csd_flash.sh").read_text(encoding="utf-8")


def test_test_idle_watchdog_tracks_non_system_disk_io_progress():
    source = Path("ci/io_progress_signature.sh").read_text(encoding="utf-8")

    assert "lsblk -nr -o NAME,PKNAME,MOUNTPOINT" in source
    assert '"/sys/block/${dev}/stat"' in source
    assert "loop*|ram*|sr*|fd*|md*|dm-*|zram*" in source
    assert 'if is_protected "${dev}"; then' in source
    assert 'awk -v dev="${dev}"' in source


def test_ci_is_manual_only_without_cron_or_auto_mr_trigger():
    source = Path("Jenkinsfile").read_text(encoding="utf-8")

    assert "cron(" not in source
    assert "triggers {" not in source
    assert "name: 'SIMULATE_AUTO_MR_TRIGGER'" not in source
    assert "automaticMrTriggered" not in source
    assert "useQemuVmTarget" not in source
    assert "triggerSource = 'kernel_driver Merge Request'" not in source
    assert "merge_requests?state=opened" not in source
    assert "kernel_driver_open_mrs" not in source
    assert "existingMrShaChanged || newlyCreatedMr" not in source
    assert "manual CI build" in source


def test_draid_module_reload_retries_and_reports_memory_on_insmod_failure():
    source = pipeline_sources()

    assert "echo 3 >/proc/sys/vm/drop_caches" in source
    assert "memory status after insmod failure" in source
    assert "dmesg tail after insmod failure" in source
    assert "VmallocTotal" in source


def test_draid_controller_state_check_and_reset_are_disabled():
    source = Path("ci/prepare_draid_driver.sh").read_text(encoding="utf-8")
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
    assert "dpkg --print-architecture" in source
    assert 'if [ "${architecture}" = "amd64" ]; then' in source
    assert "99raid-nvme-native-architecture" in source
    assert 'APT::Architecture "amd64";' in source
    assert 'APT::Architectures { "amd64"; };' in source
    assert "dpkg --remove-architecture" not in source
    assert "keep registered foreign architectures unchanged" in source
    assert "arm64|armhf" in source
    assert "mirrors\\.aliyun\\.com/ubuntu" in source
    assert "ubuntu-ports" in source
    assert "apt_retry apt-get -o DPkg::Lock::Timeout=600 update" in source
    assert "fio nvme-cli pciutils util-linux smartmontools sdparm" in source
    assert "sysstat gawk nmap bc psmisc numactl lsscsi unzip" in source
    assert "xfsprogs parted make gcc g++" in source
    assert "python3-pip python3-pytest python-is-python3" in source
    assert "for tool in fio nvme lspci findmnt lsblk; do" in source
    assert "Missing required test tools after auto install" in source


def test_run_tests_uses_plain_host_ssh_without_qemu_ports():
    source = Path("Jenkinsfile").read_text(encoding="utf-8")

    assert 'def targetSsh = "ssh ${env.SSH_OPTS} ${env.TARGET_USER}@${ip}"' in source
    assert 'def targetScp = "scp ${env.SSH_OPTS}"' in source
    assert "sshpass" not in source
    assert "${targetSsh} 'rm -rf ${remoteDir} && mkdir -p ${remoteDir}'" in source
    assert "find /root/Cyril/Jenkins -maxdepth 1 -type d -name" not in source
    assert "jenkins_nvme_*" not in source


def test_draid_driver_and_test_dependency_steps_target_physical_host_only():
    source = Path("Jenkinsfile").read_text(encoding="utf-8")

    assert "QEMU_VM_TARGET" not in source
    assert "ci/prepare_draid_driver.sh" in source
    assert "ci/install_test_dependencies.sh" in source


def test_run_remote_test_reports_error_without_qemu_scene_keep_message():
    source = Path("Jenkinsfile").read_text(encoding="utf-8")

    assert "keep VM/vfio devices for failure analysis" not in source
    assert "Next triggered run will reclaim them in pre-test cleanup" not in source
    assert 'error "[${ip}] nvme_raid_test.py or report collection failed with exit code ${testStatus}"' in source


def test_junit_glob_only_collects_node_level_reports():
    source = Path("Jenkinsfile").read_text(encoding="utf-8")

    assert "junit testResults: 'report_*.*.*.*.xml', allowEmptyResults: true" in source
    assert "report_*_physical.xml" not in source
