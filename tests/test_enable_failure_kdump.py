from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
KDUMP_SCRIPT = REPO_ROOT / "ci" / "enable_failure_kdump.sh"


def test_kdump_script_configures_crashkernel_and_path():
    source = KDUMP_SCRIPT.read_text(encoding="utf-8")
    assert "crashkernel" in source
    assert "kdump-tools" in source or "kexec-tools" in source
    assert "failure_bundles/kdump" in source
    assert "kdump_reboot_required" in source
    assert "exit 0" in source


def test_prepare_and_install_enable_kdump():
    install = (REPO_ROOT / "ci" / "install_test_dependencies.sh").read_text(encoding="utf-8")
    prepare = (REPO_ROOT / "ci" / "prepare_env.sh").read_text(encoding="utf-8")
    remote = (REPO_ROOT / "ci" / "run_remote_test_and_collect.sh").read_text(encoding="utf-8")
    collect = (REPO_ROOT / "ci" / "collect_failure_bundle.sh").read_text(encoding="utf-8")
    assert "enable_failure_kdump.sh" in install
    assert "kdump-tools" in install or "kexec-tools" in install
    assert "enable_failure_kdump.sh" in prepare
    assert "enable_failure_kdump.sh" in remote
    assert "snapshot_kdump_artifacts" in collect
    assert "KDUMP_COPY_VMCORE" in collect
