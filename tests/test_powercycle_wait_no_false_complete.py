"""wait must not treat SSH errors / premature markers as completion."""
from pathlib import Path


def test_item_completed_requires_marker_substring_and_cycle_check():
    src = Path("powercycle/wait_powercycle_completion.sh").read_text(encoding="utf-8")
    body = src.split("item_completed()", 1)[1].split("item_triggered()", 1)[0]
    assert '== *"all power-cycle loops completed"*' in body
    assert '== *"Power-cycle test completed all"*' in body
    assert "last_loop" in body
    assert "ignore premature completion marker" in body
    # Old buggy form grepped with remote-only 2>/dev/null and accepted any non-empty text.
    assert 'if [[ -n "${text}" ]]; then' not in body


def test_item_failed_requires_pattern_in_match_line():
    src = Path("powercycle/wait_powercycle_completion.sh").read_text(encoding="utf-8")
    body = src.split("item_failed()", 1)[1].split("dump_remote_progress", 1)[0]
    assert '== *"${pattern}"*' in body
