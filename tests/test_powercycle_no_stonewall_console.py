"""PowerCycle: no multi-disk stonewall; remote runner prints to console without tee."""
from pathlib import Path


def test_fio_verify_does_not_inject_stonewall():
    src = Path("IO_Stress/lib/fio_verify.sh").read_text(encoding="utf-8")
    assert 'sed -i "9i stonewall"' not in src
    assert "No stonewall" in src
    assert "/^stonewall$/d" in src


def test_run_remote_test_prints_console_without_tee():
    src = Path("powercycle/run_remote_test_and_collect.sh").read_text(encoding="utf-8")
    assert "| tee " not in src
    assert "tee -a" not in src
    assert "console_print" in src
    assert "stream_dut_runtime_logs_once" in src
