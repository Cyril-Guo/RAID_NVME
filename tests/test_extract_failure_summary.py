import json

from ci import extract_failure_summary


def test_failure_summary_collects_junit_and_watchdog_errors(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "report_192.168.22.134.xml").write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<testsuite name="pytest">
  <testcase classname="test_items.test_smoke" name="test_basic_io">
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


def test_main_writes_summary_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "environment_prepare_10.0.0.1.log").write_text(
        "ERROR: insmod ./draid.ko failed\nENVIRONMENT_PREPARE_STATUS=failed\n",
        encoding="utf-8",
    )

    assert extract_failure_summary.main([]) == 0
    assert "insmod ./draid.ko failed" in (tmp_path / "failure_summary.txt").read_text(encoding="utf-8")


def test_failure_summary_includes_native_allure_failure(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    allure_dir = tmp_path / "allure-results"
    allure_dir.mkdir()
    (allure_dir / "native-result.json").write_text(
        json.dumps(
            {
                "name": "test_mix_stress",
                "status": "broken",
                "statusDetails": {"message": "BrokenPipeError: fio output pipe closed"},
            }
        ),
        encoding="utf-8",
    )

    summary = extract_failure_summary.failure_summary()

    assert "test_mix_stress" in summary
    assert "BrokenPipeError" in summary
