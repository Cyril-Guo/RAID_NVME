from ci.build_status import is_manual_abort_text


def test_detects_jenkins_manual_abort_line():
    assert is_manual_abort_text("Running tests\nAborted by cyril\n")
    assert is_manual_abort_text("[2026-09-04 12:00:00] Aborted by cyril\n")


def test_does_not_treat_automatic_idle_timeout_as_manual_abort():
    assert not is_manual_abort_text(
        "idle watchdog fired after 15 minutes without progress\nFinished: FAILURE\n"
    )
