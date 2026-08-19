from pathlib import Path


def test_prepare_physical_io_case_script_covers_required_steps():
    source = Path("ci/prepare_physical_io_case.sh").read_text(encoding="utf-8")

    flash_clear_lines = [
        line.strip()
        for line in source.splitlines()
        if "clear_8p_csd_flash.sh" in line or "flash-clear.sh" in line
    ]
    assert flash_clear_lines
    assert all(line.startswith("#") for line in flash_clear_lines)
    assert "skip dirty CSD flash clear" in source
    assert "artifacts/dpraid" in source
    assert "rmmod" in source
    assert "insmod" in source
    assert "restore_physical_raid_state.sh" in source


def test_install_dpraid_stages_artifact_for_per_case_refresh():
    source = Path("ci/install_dpraid_remote.sh").read_text(encoding="utf-8")

    assert "REMOTE_DIR" in source
    assert "artifacts/dpraid" in source
    assert ">/dev/null 2>&1 || true" not in source
    assert "/usr/bin/dpraid --help >/dev/null" in source


def test_prepare_physical_io_case_requires_working_dpraid_help():
    source = Path("ci/prepare_physical_io_case.sh").read_text(encoding="utf-8")

    assert "/usr/bin/dpraid --help >/dev/null" in source
    assert "/usr/bin/dpraid --help >/dev/null 2>&1 || true" not in source
