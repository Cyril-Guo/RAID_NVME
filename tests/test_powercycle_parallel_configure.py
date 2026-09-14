"""Parallel powercycle path must generate *.log jobs before running phases."""
from pathlib import Path


def test_do_fio_configures_before_parallel_phases():
    source = Path("IO_Stress/lib/fio.sh").read_text(encoding="utf-8")
    marker = "using parallel powercycle phases"
    idx = source.index(marker)
    window = source[max(0, idx - 1200) : idx]
    assert "configure" in window
    assert "generated job configs count" in window
    needle = chr(10) + "                configure" + chr(10)
    configure_at = source.rfind(needle, 0, idx)
    run_at = source.index("run_powercycle_parallel_phases 2>&1", max(0, idx - 400))
    assert configure_at != -1
    assert configure_at < run_at
