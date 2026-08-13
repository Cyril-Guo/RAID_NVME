from pathlib import Path


def test_prepare_physical_io_case_script_covers_required_steps():
    source = Path("ci/prepare_physical_io_case.sh").read_text(encoding="utf-8")

    assert "clear_8p_csd_flash.sh" in source
    assert "artifacts/dpraid" in source
    assert "rmmod" in source
    assert "insmod" in source
    assert "restore_physical_raid_state.sh" in source


def test_install_dpraid_stages_artifact_for_per_case_refresh():
    source = Path("ci/install_dpraid_remote.sh").read_text(encoding="utf-8")

    assert "REMOTE_DIR" in source
    assert "artifacts/dpraid" in source
