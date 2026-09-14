"""Parallel powercycle path must generate *.log jobs before running phases."""
from pathlib import Path


def test_do_fio_configures_before_parallel_phases():
    source = Path("IO_Stress/lib/fio.sh").read_text(encoding="utf-8")
    marker = "using parallel powercycle phases"
    idx = source.index(marker)
    window = source[max(0, idx - 1400) : idx + 200]
    assert "generated job configs count" in window
    assert "if ! configure; then" in window
    configure_at = window.index("if ! configure; then")
    run_at = window.index("run_powercycle_parallel_phases 2>&1")
    assert configure_at < run_at
