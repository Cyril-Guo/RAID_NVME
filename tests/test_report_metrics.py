import json

from ci import report_metrics


def test_report_metrics_counts_testcase_nodes_when_testsuites_root_is_zero(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "report_192.168.22.134.xml").write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<testsuites tests="0" failures="0" errors="0" skipped="0">
  <testsuite name="pytest">
    <testcase classname="test_items.test_smoke_03_lawdisk" name="test_lawdiskstress" />
    <testcase classname="test_items.test_smoke_04_mix" name="test_mix_stress">
      <failure message="fio failed">trace</failure>
    </testcase>
    <testcase classname="test_items.test_smoke_05_reboot" name="test_reboot_powercycle">
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
                "name": "Test_Execution_QEMU_192.168.22.134",
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


def test_report_metrics_counts_each_failed_env_log_as_one_item(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "environment_prepare_192.168.22.125.log").write_text(
        "ERROR: QEMU VM startup failed\nENVIRONMENT_PREPARE_STATUS=failed\n",
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


def test_report_metrics_uses_worst_status_across_junit_and_native_allure(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "report_192.168.22.134.xml").write_text(
        '<testsuite><testcase classname="x" name="test_basic_io" /></testsuite>',
        encoding="utf-8",
    )
    (tmp_path / "test_execution_192.168.22.134.log").write_text(
        "TEST_EXECUTION_TARGET=physical\n", encoding="utf-8"
    )
    allure_dir = tmp_path / "allure-results"
    allure_dir.mkdir()
    (allure_dir / "native-result.json").write_text(
        json.dumps(
            {
                "name": "basic_io",
                "fullName": "physical:192.168.22.134:x#test_basic_io",
                "status": "failed",
                "labels": [
                    {"name": "host", "value": "192.168.22.134"},
                    {"name": "target", "value": "physical"},
                ],
            }
        ),
        encoding="utf-8",
    )

    assert report_metrics.report_metrics() == {
        "tests": 1,
        "failures": 1,
        "errors": 0,
        "skipped": 0,
        "kind": "tests",
    }
