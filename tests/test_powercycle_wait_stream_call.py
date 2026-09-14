"""wait must call stream_all_runtime_logs with a normal quoted run_key."""
from pathlib import Path


def test_stream_calls_are_not_backslash_escaped():
    src = Path("powercycle/wait_powercycle_completion.sh").read_text(encoding="utf-8")
    bad = [ln for ln in src.splitlines() if "stream_all_runtime_logs" in ln and "\\" in ln]
    assert not bad, bad
    needle = "stream_all_runtime_logs " + '"${run_key}"'
    good = [ln for ln in src.splitlines() if needle in ln]
    assert len(good) >= 1, needle
