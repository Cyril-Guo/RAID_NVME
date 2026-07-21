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


def test_feishu_webhook_uses_jenkins_credential():
    source = Path("Jenkinsfile").read_text(encoding="utf-8")

    assert "FEISHU_WEBHOOK = credentials('feishu-webhook')" in source
    assert "https://open.feishu.cn/open-apis/bot/v2/hook/" not in source


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

    assert "TARGET_NODE_TIMEOUT_MINUTES = '90'" in source
    assert "ServerAliveInterval=30" in source
    assert "ServerAliveCountMax=3" in source
    assert "ConnectTimeout=15" in source
    assert 'timeout --kill-after=60s "${TARGET_NODE_TIMEOUT_MINUTES}m"' in source
    assert "${test_label} timed out after ${TARGET_NODE_TIMEOUT_MINUTES} minutes" in source
    assert 'exit "${test_rc}"' in source


def test_automatic_mr_uses_qemu_vm_without_changing_manual_mr():
    source = pipeline_sources()

    assert "useQemuVmTarget = params.SIMULATE_AUTO_MR_TRIGGER" in source
    assert "useQemuVmTarget = true" in source
    assert "'Manual MR Build (Simulate Auto MR)' : 'Manual MR Build'" in source
    assert "triggerSource = 'kernel_driver Merge Request'" in source
    assert "QEMU_VM_SSH_PORT = '2233'" in source
    assert "QEMU_VM_SCP_PORT = '2233'" in source
    assert "QEMU_KERNEL_BUILD_DIR = '/root/gr/qemu/general_kernel'" in source
    assert "cd \"${QEMU_VM_WORKDIR}\"" in source
    assert "\"${QEMU_VM_START_SCRIPT}\"" in source
    assert "QEMU_VM_TARGET=${qemuEnv}" in source
    assert "sshpass is required on Jenkins server for QEMU VM login, and automatic install failed" in source


def test_automatic_mr_signature_only_tracks_code_sha():
    source = pipeline_sources()

    assert 'f"{mr.get(\'iid\')}:{mr.get(\'sha\')}"' in source
    assert 'f"{mr.get(\'iid\')}:{mr.get(\'updated_at\')}:{mr.get(\'sha\')}"' not in source
    assert 'parts.size() >= 3 ? "${parts[0]}:${parts[-1]}" : signature' in source
    assert "hasNewOpenMrEvent = currentSignatures.any" in source


def test_qemu_vm_installs_sshpass_on_jenkins_server():
    source = pipeline_sources()

    assert "sshpass is missing on Jenkins server, try to install it automatically." in source
    assert "sudo apt-get -o DPkg::Lock::Timeout=600 install -y sshpass" in source
    assert "sudo dnf install -y sshpass" in source
    assert "sudo yum install -y sshpass" in source
    assert "sudo zypper install -y sshpass" in source


def test_qemu_vm_start_is_skipped_when_vm_is_already_running():
    source = pipeline_sources()

    assert "qemu vm already running" in source
    assert "QEMU VM is already running, skip vfio bind and ${QEMU_VM_START_SCRIPT}" in source
    assert "dpraid_${BUILD_NUMBER}_host_prepare" in source
    assert "restore physical host RAID state before QEMU handoff" in source
    assert "\"${QEMU_VM_START_SCRIPT}\"" in source
    assert "QEMU VM SSH is ready" in source


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
    assert "bind NVMe PCI device to QEMU vfio" in source
    assert "skip invalid QEMU vfio device" in source
    assert '[ ! -e "/dev/vfio/${group}" ]' in source
    assert "no usable QEMU vfio NVMe devices after bind validation" in source
    assert "QEMU_ALLOWED_VFIO_FILE" in source
    assert "skip QEMU vfio device not in validated list" in source
    assert "skip QEMU vfio device without vfio node" in source
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
    assert "tar -czf - -C kernel_driver/drivers/draid ." in source
    assert 'make -C "${QEMU_KERNEL_BUILD_DIR}" M="${host_build_dir}" modules' in source
    assert 'target_scp "${local_module}"' in source


def test_qemu_vm_shell_variables_are_escaped_for_groovy():
    source = pipeline_sources()

    assert 'command -v "$tool"' in source
    assert 'missing_tools="${missing_tools} ${tool}"' in source
    assert 'after auto install:${missing_tools}' in source
