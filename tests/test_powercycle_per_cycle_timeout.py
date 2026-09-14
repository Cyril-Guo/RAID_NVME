"""wait fails when a single cycle stalls beyond PER_CYCLE budget."""
from pathlib import Path


def test_wait_has_per_cycle_stall_fail():
    src = Path("powercycle/wait_powercycle_completion.sh").read_text(encoding="utf-8")
    assert "POWER_CYCLE_PER_CYCLE_TIMEOUT_MINUTES:-120" in src
    assert "cycles * per_cycle_min" in src
    assert "no cycle progress for" in src
    assert "read_remote_reboot_loop" in src
    assert "last_progress_ts" in src
