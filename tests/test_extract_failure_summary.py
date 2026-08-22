from ci import extract_failure_summary


def test_failure_summary_collects_junit_and_watchdog_errors(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "report_192.168.22.134.xml").write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<testsuite name="pytest">
  <testcase classname="test_items.test_ci" name="test_basic_io">
    <failure message="FIO verification failed">AssertionError: bad data</failure>
  </testcase>
</testsuite>
""",
        encoding="utf-8",
    )
    (tmp_path / "test_execution_192.168.22.134.log").write_text(
        "[2026-07-28 21:23:28] ERROR: idle watchdog fired after 15 minutes; target may be hung.\n"
        "TEST_EXECUTION_STATUS=failed\n",
        encoding="utf-8",
    )

    summary = extract_failure_summary.failure_summary()

    assert "test_basic_io: FIO verification failed" in summary
    assert "idle watchdog fired after 15 minutes" in summary
    assert "TEST_EXECUTION_STATUS" not in summary


def test_failure_summary_ignores_zero_failure_counters():
    text = "0 failed, 0 errors\nfailed=0\nERROR: real failure\n"

    assert extract_failure_summary.extract_failure_lines(text) == ["ERROR: real failure"]


def test_failure_summary_ignores_kernel_header_error_comments():
    text = (
        '#define KERN_ERR KERN_SOH "3" /* error conditions */\n'
        "ENVIRONMENT_PREPARE_STATUS=passed\n"
        "ERROR: insmod ./draid.ko failed\n"
    )

    assert extract_failure_summary.extract_failure_lines(text) == [
        "ERROR: insmod ./draid.ko failed"
    ]


def test_main_writes_summary_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "environment_prepare_10.0.0.1.log").write_text(
        "ERROR: insmod ./draid.ko failed\nENVIRONMENT_PREPARE_STATUS=failed\n",
        encoding="utf-8",
    )

    assert extract_failure_summary.main([]) == 0
    assert "insmod ./draid.ko failed" in (tmp_path / "failure_summary.txt").read_text(encoding="utf-8")


def test_failure_summary_prioritizes_fio_model_elapsed_lines():
    text = (
        "Job 2/4 is Running..\n"
        "some other error happened\n"
        "FIO command failed, model=randwrite bs=4k qd=64 runtime=30s (#2), "
        "config=2-randwrite-4k-64-30.log, elapsed=12s(12s), planned_runtime=30s, rc=8\n"
    )

    lines = extract_failure_summary.extract_failure_lines(text, limit=2)

    assert lines[0].startswith("FIO command failed, model=randwrite")
    assert "elapsed=12s" in lines[0]
