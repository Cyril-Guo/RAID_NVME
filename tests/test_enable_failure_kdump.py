from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
KDUMP_SCRIPT = REPO_ROOT / "vd_io" / "enable_failure_kdump.sh"


def test_kdump_script_configures_crashkernel_and_path():
    source = KDUMP_SCRIPT.read_text(encoding="utf-8")
    assert "crashkernel" in source
    assert "kdump-tools" in source or "kexec-tools" in source
    assert "failure_bundles/kdump" in source
    assert "kdump_reboot_required" in source
    assert "exit 0" in source


def test_prepare_and_install_enable_kdump():
    install = (REPO_ROOT / "vd_io" / "install_test_dependencies.sh").read_text(encoding="utf-8")
    prepare = (REPO_ROOT / "vd_io" / "prepare_env.sh").read_text(encoding="utf-8")
    remote = (REPO_ROOT / "vd_io" / "run_remote_test_and_collect.sh").read_text(encoding="utf-8")
    collect = (REPO_ROOT / "vd_io" / "collect_failure_bundle.sh").read_text(encoding="utf-8")
    # Packages still come from install; arming is prepare_env (once) + run_remote (pre-test).
    assert "kdump-tools" in install or "kexec-tools" in install
    assert "enable_failure_kdump.sh" in prepare
    assert prepare.count('ENABLE_KDUMP=1 "${SCRIPT_DIR}/enable_failure_kdump.sh"') == 1
    assert "enable_failure_kdump.sh" in remote
    assert "snapshot_kdump_artifacts" in collect
    assert "KDUMP_COPY_VMCORE" in collect


def test_kdump_defaults_enabled_and_rewrites_coredir():
    source = KDUMP_SCRIPT.read_text(encoding="utf-8")
    assert "ENABLE_KDUMP=${ENABLE_KDUMP:-1}" in source
    assert "Always rewrite COREDIR" in source
    remote = (REPO_ROOT / "vd_io" / "run_remote_test_and_collect.sh").read_text(encoding="utf-8")
    assert "ENABLE_KDUMP=1 vd_io/enable_failure_kdump.sh" in remote
    # Must not leave the enable call commented out.
    for line in remote.splitlines():
        if "ENABLE_KDUMP=1 vd_io/enable_failure_kdump.sh" in line:
            assert not line.lstrip().startswith("#"), line
    prepare = (REPO_ROOT / "vd_io" / "prepare_env.sh").read_text(encoding="utf-8")
    assert "ENABLE_KDUMP=1" in prepare
    install = (REPO_ROOT / "vd_io" / "install_test_dependencies.sh").read_text(encoding="utf-8")
    draid = (REPO_ROOT / "vd_io" / "prepare_draid_driver.sh").read_text(encoding="utf-8")
    assert "enable_failure_kdump.sh" not in install
    assert "enable_failure_kdump.sh" not in draid
