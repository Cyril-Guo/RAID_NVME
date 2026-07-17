from pathlib import Path


def test_apt_get_waits_for_dpkg_lock():
    source = Path("Jenkinsfile").read_text(encoding="utf-8")

    assert source.count("DPkg::Lock::Timeout=600") >= 4
    assert "apt-get -o DPkg::Lock::Timeout=600 update" in source
    assert "apt-get -o DPkg::Lock::Timeout=600 install -y build-essential" in source
    assert "apt-get -o DPkg::Lock::Timeout=600 install -y python3-pip python3-pytest" in source


def test_debug_no_feishu_only_skips_notification():
    source = Path("Jenkinsfile").read_text(encoding="utf-8")

    assert "name: 'DEBUG_NO_FEISHU'" in source
    assert "DEBUG_NO_FEISHU=true, skip Feishu notification." in source
    assert "writeFile file: 'feishu_payload.json'" in source


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
    assert "triggerSource = 'Manual MR Build'" in source
    assert "Manual build requested. Run smoke tests on kernel_driver/${kernelDriverRef}." in source
