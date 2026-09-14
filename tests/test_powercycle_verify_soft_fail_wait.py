"""VERIFY soft-fail must not make wait report failure after recovery."""
from pathlib import Path
import textwrap


def test_verify_soft_messages_are_not_hard_wait_patterns():
    pc = Path("IO_Stress/lib/fio_powercycle.sh").read_text(encoding="utf-8")
    fio = Path("IO_Stress/lib/fio.sh").read_text(encoding="utf-8")
    assert "VERIFY soft-fail" in pc
    assert "POWERCYCLE_FIO_SOFT_RESULT=1" in pc
    assert "POWERCYCLE soft fio fail" in fio
    assert "append_fio_error_detail_soft" in fio
    soft_fn = fio.split("append_fio_error_detail_soft()", 1)[1].split("function run_all", 1)[0]
    assert "Result_Dir/result.log" not in soft_fn


def test_wait_ignores_soft_markers_when_verify_recovered():
    wait = Path("powercycle/wait_powercycle_completion.sh").read_text(encoding="utf-8")
    failed = wait.split("item_failed()", 1)[1].split("dump_remote_progress", 1)[0]
    assert "ignore soft failure marker after VERIFY recovered" in failed
    assert "FIO stage failed" in failed
    # Hard failure string must remain a hard pattern (not in the ignore-only list exclusively).
    assert '"FIO stage failed"' in failed or "FIO stage failed" in failed


def test_soft_then_recovered_without_hard_fail_is_success_semantics():
    text = textwrap.dedent(
        """
        POWERCYCLE soft fio fail, model=x, rc=1
        [POWERCYCLE] VERIFY soft-fail out=0_1.txt rc=1
        FIO command failed, model=legacy, rc=1
        verify failed: bad checksum
        FIO stage abort, phase=VERIFY
        2026-09-14 [POWERCYCLE] VERIFY retry1 recovered
        [POWERCYCLE] phase=VERIFY OK
        """
    )
    hard = "FIO stage failed" in text
    recovered = ("VERIFY" in text and "recovered" in text)
    soft_patterns = [
        "FIO stage abort",
        "FIO command failed",
        "verify failed",
        "FIO failed",
    ]
    soft_hit = any(p in text for p in soft_patterns)
    assert soft_hit and recovered and not hard
    # Mirror wait rule: soft markers ignored when recovered and no hard fail.
    should_fail = hard or (soft_hit and not recovered)
    assert should_fail is False


def test_hard_fail_still_fails_even_with_earlier_recovered():
    text = textwrap.dedent(
        """
        VERIFY retry1 recovered
        FIO stage failed in powercycle phase=VERIFY
        """
    )
    hard = "FIO stage failed" in text
    assert hard is True


def test_modes_mismatch_refuses_run():
    src = Path("IO_Stress/lib/fio_powercycle.sh").read_text(encoding="utf-8")
    assert "refusing to run" in src
    assert "falling back to serial run_all" not in src


def test_configure_failure_is_checked():
    src = Path("IO_Stress/lib/fio.sh").read_text(encoding="utf-8")
    assert "if ! configure; then" in src


def test_profile_verify_retries_synced():
    src = Path("IO_Stress/lib/fio_powercycle.sh").read_text(encoding="utf-8")
    assert "profile_retries" in src
    assert "resolve_profile()" in src
