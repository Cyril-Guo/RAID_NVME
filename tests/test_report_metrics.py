import json

from ci import report_metrics


def test_report_metrics_counts_testcase_nodes_when_testsuites_root_is_zero(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "report_192.168.22.134.xml").write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<testsuites tests="0" failures="0" errors="0" skipped="0">
  <testsuite name="pytest">
    <testcase classname="test_items.test_ci_03_lawdisk" name="test_lawdiskstress" />
    <testcase classname="test_items.test_ci_04_mix" name="test_mix_stress">
      <failure message="fio failed">trace</failure>
    </testcase>
    <testcase classname="test_items.test_ci_05_reboot" name="test_reboot_powercycle">
      <error message="setup failed">trace</error>
    </testcase>
  </testsuite>
</testsuites>
""",
        encoding="utf-8",
    )

    assert report_metrics.report_metrics() == {
        "tests": 3,
        "failures": 1,
        "errors": 1,
        "skipped": 0,
        "kind": "tests",
    }


def test_report_metrics_falls_back_to_allure_results(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    allure_dir = tmp_path / "allure-results"
    allure_dir.mkdir()
    for index, status in enumerate(("passed", "failed", "broken", "skipped")):
        (allure_dir / f"{index}-result.json").write_text(
            json.dumps({"name": f"case_{index}", "status": status}),
            encoding="utf-8",
        )

    assert report_metrics.report_metrics() == {
        "tests": 4,
        "failures": 1,
        "errors": 1,
        "skipped": 1,
        "kind": "tests",
    }


def test_report_metrics_marks_environment_prepare_as_infra(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    allure_dir = tmp_path / "allure-results"
    allure_dir.mkdir()
    (allure_dir / "env-result.json").write_text(
        json.dumps(
            {
                "name": "Environment_Prepare_192.168.22.125",
                "status": "broken",
                "labels": [{"name": "suite", "value": "Environment_Prepare"}],
            }
        ),
        encoding="utf-8",
    )

    assert report_metrics.report_metrics() == {
        "tests": 1,
        "failures": 0,
        "errors": 1,
        "skipped": 0,
        "kind": "infra",
    }


def test_main_prints_kind(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    allure_dir = tmp_path / "allure-results"
    allure_dir.mkdir()
    (allure_dir / "exec-result.json").write_text(
        json.dumps(
            {
                "name": "Test_Execution_Physical_192.168.22.134",
                "status": "broken",
                "labels": [{"name": "suite", "value": "Test_Execution"}],
            }
        ),
        encoding="utf-8",
    )

    assert report_metrics.main() == 0
    assert capsys.readouterr().out.strip() == "1 0 1 0 infra"


def test_report_metrics_skips_per_item_junit_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "report_lawdisk.xml").write_text(
        """<testsuite name="pytest">
  <testcase classname="x" name="a"><failure message="x">y</failure></testcase>
</testsuite>
""",
        encoding="utf-8",
    )
    (tmp_path / "report_192.168.22.134.xml").write_text(
        """<testsuite name="pytest">
  <testcase classname="x" name="b" />
</testsuite>
""",
        encoding="utf-8",
    )

    assert report_metrics.report_metrics() == {
        "tests": 1,
        "failures": 0,
        "errors": 0,
        "skipped": 0,
        "kind": "tests",
    }


def test_report_metrics_includes_infra_allure_alongside_junit(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "report_192.168.22.134.xml").write_text(
        """<testsuite name="pytest">
  <testcase classname="x" name="a" />
</testsuite>
""",
        encoding="utf-8",
    )
    allure_dir = tmp_path / "allure-results"
    allure_dir.mkdir()
    (allure_dir / "restore-result.json").write_text(
        json.dumps(
            {
                "name": "Physical_Restore_192.168.22.134_physical",
                "status": "broken",
                "labels": [{"name": "suite", "value": "Physical_Restore"}],
            }
        ),
        encoding="utf-8",
    )

    assert report_metrics.report_metrics() == {
        "tests": 2,
        "failures": 0,
        "errors": 1,
        "skipped": 0,
        "kind": "tests",
    }


def test_report_metrics_merges_native_allure_failure_missing_from_junit(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "report_192.168.22.134.xml").write_text(
        """<testsuite name="pytest">
  <testcase classname="test_items.test_ci_06_basic_io" name="test_basic_io">
    <properties><property name="run_key" value="basic_io__1" /></properties>
  </testcase>
</testsuite>
""",
        encoding="utf-8",
    )
    allure_dir = tmp_path / "allure-results"
    allure_dir.mkdir()
    (allure_dir / "basic-result.json").write_text(
        json.dumps(
            {
                "name": "[Physical 192.168.22.134] test_basic_io",
                "fullName": "physical:192.168.22.134:test_items.test_ci_06_basic_io#test_basic_io",
                "status": "passed",
                "labels": [
                    {"name": "host", "value": "192.168.22.134"},
                    {"name": "run_key", "value": "basic_io__1"},
                ],
            }
        ),
        encoding="utf-8",
    )
    (allure_dir / "mix-result.json").write_text(
        json.dumps(
            {
                "name": "[Physical 192.168.22.134] test_mix_stress",
                "fullName": "physical:192.168.22.134:test_items.test_ci_05_mix#test_mix_stress",
                "status": "failed",
                "labels": [
                    {"name": "host", "value": "192.168.22.134"},
                    {"name": "run_key", "value": "mix__2"},
                ],
            }
        ),
        encoding="utf-8",
    )

    assert report_metrics.report_metrics() == {
        "tests": 2,
        "failures": 1,
        "errors": 0,
        "skipped": 0,
        "kind": "tests",
    }


def test_report_metrics_counts_each_failed_env_log_as_one_item(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "environment_prepare_192.168.22.125.log").write_text(
        "ERROR: draid kernel module load failed\nENVIRONMENT_PREPARE_STATUS=failed\n",
        encoding="utf-8",
    )
    (tmp_path / "environment_prepare_192.168.22.134.log").write_text(
        "ERROR: build and reload draid kernel driver failed\nENVIRONMENT_PREPARE_STATUS=failed\n",
        encoding="utf-8",
    )

    assert report_metrics.report_metrics() == {
        "tests": 2,
        "failures": 0,
        "errors": 2,
        "skipped": 0,
        "kind": "infra",
    }


def test_report_metrics_does_not_double_count_execution_when_junit_exists(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "report_192.168.22.134.xml").write_text(
        """<testsuite name="pytest">
  <testcase classname="x" name="a"><failure message="fio">trace</failure></testcase>
</testsuite>
""",
        encoding="utf-8",
    )
    (tmp_path / "test_execution_192.168.22.134.log").write_text(
        "TEST_EXECUTION_STATUS=failed\nTEST_EXECUTION_EXIT_CODE=1\n",
        encoding="utf-8",
    )

    assert report_metrics.report_metrics() == {
        "tests": 1,
        "failures": 1,
        "errors": 0,
        "skipped": 0,
        "kind": "tests",
    }


def test_report_metrics_counts_execution_failure_when_junit_only_passed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "report_192.168.22.134.xml").write_text(
        """<testsuite name="pytest">
  <testcase classname="x" name="a" />
</testsuite>
""",
        encoding="utf-8",
    )
    (tmp_path / "test_execution_192.168.22.134.log").write_text(
        "FIO command failed in MIX mode job 10, model=rw bs=4k qd=32 runtime=30s (#10), elapsed=1s, rc=96/96/96/96\n"
        "TEST_EXECUTION_STATUS=failed\nTEST_EXECUTION_EXIT_CODE=1\n",
        encoding="utf-8",
    )

    assert report_metrics.report_metrics() == {
        "tests": 2,
        "failures": 0,
        "errors": 1,
        "skipped": 0,
        "kind": "tests",
    }


def test_report_metrics_surfaces_hard_fio_fail_even_when_status_passed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "report_192.168.22.134.xml").write_text(
        """<testsuite name="pytest">
  <testcase classname="x" name="a" />
</testsuite>
""",
        encoding="utf-8",
    )
    (tmp_path / "test_execution_192.168.22.134.log").write_text(
        "FIO command failed in MIX mode job 22, model=randread bs=4m qd=32 runtime=30s (#22), "
        "elapsed=46s, rc=96/96/96/96, error_disks=8; MIX_FAIL_ON_ANY=yes, fail\n"
        "FIO stage failed in LAWDISKSTRESS mode, model=randread bs=4m qd=32 runtime=30s (#22), "
        "config=22-randread-4m-32-30.log, elapsed=46s, planned_runtime=30s, rc=1\n"
        "TEST_EXECUTION_STATUS=passed\n",
        encoding="utf-8",
    )

    assert report_metrics.report_metrics() == {
        "tests": 2,
        "failures": 0,
        "errors": 1,
        "skipped": 0,
        "kind": "tests",
    }


def test_report_metrics_does_not_count_manual_abort_as_infra_failure(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "test_execution_192.168.22.134.log").write_text("", encoding="utf-8")
    (tmp_path / "jenkins_console.log").write_text(
        "Running nvme_raid_test.py\nAborted by cyril\nFinished: ABORTED\n",
        encoding="utf-8",
    )

    assert report_metrics.report_metrics() == {
        "tests": 0,
        "failures": 0,
        "errors": 0,
        "skipped": 0,
        "kind": "empty",
    }


def test_report_metrics_still_counts_incomplete_execution_without_manual_abort(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "test_execution_192.168.22.134.log").write_text("", encoding="utf-8")

    assert report_metrics.report_metrics() == {
        "tests": 1,
        "failures": 0,
        "errors": 1,
        "skipped": 0,
        "kind": "infra",
    }


def test_report_metrics_keeps_real_failure_before_manual_abort(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "test_execution_192.168.22.134.log").write_text(
        "idle watchdog fired after 15 minutes without progress\n"
        "TEST_EXECUTION_STATUS=failed\n",
        encoding="utf-8",
    )
    (tmp_path / "jenkins_console.log").write_text("Aborted by cyril\n", encoding="utf-8")

    assert report_metrics.report_metrics() == {
        "tests": 1,
        "failures": 0,
        "errors": 1,
        "skipped": 0,
        "kind": "infra",
    }
