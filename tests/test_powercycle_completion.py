from pathlib import Path


def test_powercycle_completion_has_success_path():
    fio_source = Path("IO_Stress/lib/fio.sh").read_text(encoding="utf-8")
    run_source = Path("IO_Stress/run_fio.sh").read_text(encoding="utf-8")

    assert "all power-cycle loops completed" in fio_source
    assert "return 2" in fio_source
    assert "reboot_rc -eq 2" in run_source
    assert "Power-cycle test completed all $LOOP loops." in run_source
    assert "test_end" in run_source
