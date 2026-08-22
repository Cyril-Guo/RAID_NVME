from pathlib import Path


def test_prepare_env_script_covers_smoke_physical_steps():
    source = Path("ci/prepare_env.sh").read_text(encoding="utf-8")

    assert "clear_8p_csd_flash.sh" in source
    assert "flash-clear.sh" in source
    assert "skip dirty CSD flash clear" not in source
    assert "artifacts/dpraid" in source
    assert "rmmod" in source
    assert "insmod" in source
    assert "restore_physical_raid_state.sh" in source
    assert "/usr/bin/dpraid --help >/dev/null" in source
    assert "/usr/bin/dpraid --help >/dev/null 2>&1 || true" not in source


def test_install_dpraid_stages_artifact_for_env_prepare():
    source = Path("ci/install_dpraid_remote.sh").read_text(encoding="utf-8")

    assert "REMOTE_DIR" in source
    assert "artifacts/dpraid" in source
    assert ">/dev/null 2>&1 || true" not in source
    assert "/usr/bin/dpraid --help >/dev/null" in source


def test_legacy_prepare_physical_io_case_script_removed():
    assert not Path("ci/prepare_physical_io_case.sh").exists()
    assert Path("ci/prepare_env.sh").is_file()
