import json

from ci import junit_to_allure


def test_junit_to_allure_generates_case_and_attaches_monitor(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    allure_dir = tmp_path / "allure-results"
    allure_dir.mkdir()
    (tmp_path / "report_192.168.22.134.xml").write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<testsuite name="pytest" tests="1">
  <testcase classname="test_items.test_smoke_03_lawdisk" name="test_lawdiskstress" />
</testsuite>
""",
        encoding="utf-8",
    )
    (allure_dir / "monitor_attachments.json").write_text(
        json.dumps(
            [
                {
                    "item": "lawdisk",
                    "attachment": {
                        "name": "monitor_log_lawdisk",
                        "source": "monitor_log_lawdisk.tar.gz",
                        "type": "application/gzip",
                    },
                }
            ]
        ),
        encoding="utf-8",
    )

    assert junit_to_allure.main() == 0

    results = list(allure_dir.glob("*-result.json"))
    assert len(results) == 1
    result = json.loads(results[0].read_text(encoding="utf-8"))
    assert result["name"] == "[Physical 192.168.22.134] test_lawdiskstress"
    assert result["attachments"][0]["source"] == "monitor_log_lawdisk.tar.gz"

    assert junit_to_allure.main() == 0
    assert len(list(allure_dir.glob("*-result.json"))) == 1


def test_junit_to_allure_attaches_console_snapshot(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BUILD_URL", "http://jenkins/job/SMOKE/12/")
    allure_dir = tmp_path / "allure-results"
    allure_dir.mkdir()
    (tmp_path / "report_192.168.22.134.xml").write_text(
        """<testsuite name="pytest">
  <testcase classname="test_items.test_smoke" name="test_basic_io" />
</testsuite>
""",
        encoding="utf-8",
    )
    (tmp_path / "jenkins_console.log").write_text(
        "[Pipeline] stage\nall console output\n",
        encoding="utf-8",
    )

    assert junit_to_allure.main() == 0

    result_path = next(allure_dir.glob("*-result.json"))
    result = json.loads(result_path.read_text(encoding="utf-8"))
    console_attachment = next(
        item for item in result["attachments"] if item["name"] == "终端输出"
    )
    assert "all console output" in (allure_dir / console_attachment["source"]).read_text(encoding="utf-8")
    assert "links" not in result


def test_junit_to_allure_large_console_uses_english_hint(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    allure_dir = tmp_path / "allure-results"
    allure_dir.mkdir()
    (tmp_path / "report_192.168.22.134.xml").write_text(
        """<testsuite name="pytest">
  <testcase classname="test_items.test_smoke" name="test_basic_io" />
</testsuite>
""",
        encoding="utf-8",
    )
    (tmp_path / "jenkins_console.log").write_text("x" * (1024 * 1024 + 8), encoding="utf-8")

    assert junit_to_allure.main() == 0

    result = json.loads(next(allure_dir.glob("*-result.json")).read_text(encoding="utf-8"))
    hint = next(item for item in result["attachments"] if item["name"] == "终端输出")
    full = next(item for item in result["attachments"] if item["name"] == "终端输出.log")
    assert "Content is too large, please refer to the attachment." in (
        allure_dir / hint["source"]
    ).read_text(encoding="utf-8")
    assert (allure_dir / full["source"]).stat().st_size > 1024 * 1024



def test_junit_to_allure_attaches_fio_job_summary(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    allure_dir = tmp_path / "allure-results"
    allure_dir.mkdir()
    (tmp_path / "report_192.168.23.94.xml").write_text(
        """<testsuite name="pytest">
  <testcase classname="test_items.test_smoke_05_mix" name="test_mix_stress" />
</testsuite>
""",
        encoding="utf-8",
    )
    (tmp_path / "test_execution_192.168.23.94.log").write_text(
        "\n".join(
            [
                "Job 1/2800 is Running..",
                "Job 61/2800 is Running..",
                "Job 2800/2800 is Running..",
                "[FIO] finish model=randrw (#2800) rc=0 elapsed=31s",
                "",
            ]
        ),
        encoding="utf-8",
    )

    assert junit_to_allure.main() == 0

    result = json.loads(next(allure_dir.glob("*-result.json")).read_text(encoding="utf-8"))
    summary_attachment = next(
        item for item in result["attachments"] if item["name"] == "FIO 任务摘要"
    )
    summary = (allure_dir / summary_attachment["source"]).read_text(encoding="utf-8")
    assert "job_running_lines=3" in summary
    assert "Job 2800/2800 is Running.." in summary


def test_junit_to_allure_generates_environment_prepare_result(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    allure_dir = tmp_path / "allure-results"
    allure_dir.mkdir()
    (tmp_path / "environment_prepare_192.168.22.134.log").write_text(
        "build and reload draid kernel driver\n"
        "insmod ./draid.ko failed\n"
        "ENVIRONMENT_PREPARE_STATUS=failed\n",
        encoding="utf-8",
    )

    assert junit_to_allure.main() == 0

    results = [json.loads(path.read_text(encoding="utf-8")) for path in allure_dir.glob("*-result.json")]
    env_result = next(result for result in results if result["name"] == "Environment_Prepare_192.168.22.134")
    assert env_result["status"] == "broken"
    assert env_result["labels"][0] == {"name": "suite", "value": "Environment_Prepare"}
    attachment = allure_dir / env_result["attachments"][0]["source"]
    assert "insmod ./draid.ko failed" in attachment.read_text(encoding="utf-8")


def test_junit_to_allure_does_not_count_successful_environment_prepare_as_test(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    allure_dir = tmp_path / "allure-results"
    allure_dir.mkdir()
    (tmp_path / "environment_prepare_192.168.22.134.log").write_text(
        "driver loaded\nENVIRONMENT_PREPARE_STATUS=passed\n",
        encoding="utf-8",
    )

    assert junit_to_allure.main() == 0
    assert list(allure_dir.glob("*-result.json")) == []


def test_junit_to_allure_generates_physical_restore_result(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    allure_dir = tmp_path / "allure-results"
    allure_dir.mkdir()
    (tmp_path / "environment_prepare_192.168.22.134_physical.log").write_text(
        "ENVIRONMENT_PREPARE_STATUS=passed\n"
        "restore physical host RAID state failed\n"
        "PHYSICAL_RESTORE_STATUS=failed\n",
        encoding="utf-8",
    )

    assert junit_to_allure.main() == 0

    results = [json.loads(path.read_text(encoding="utf-8")) for path in allure_dir.glob("*-result.json")]
    restore = next(result for result in results if result["name"] == "Physical_Restore_192.168.22.134_physical")
    assert restore["status"] == "broken"
    assert restore["labels"][0] == {"name": "suite", "value": "Physical_Restore"}
    assert {"name": "host", "value": "192.168.22.134"} in restore["labels"]


def test_junit_to_allure_skips_per_item_junit_reports(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    allure_dir = tmp_path / "allure-results"
    allure_dir.mkdir()
    (tmp_path / "report_lawdisk.xml").write_text(
        """<testsuite name="pytest">
  <testcase classname="test_items.test_smoke_03_lawdisk" name="test_lawdiskstress" />
</testsuite>
""",
        encoding="utf-8",
    )

    assert junit_to_allure.main() == 0
    assert list(allure_dir.glob("*-result.json")) == []


def test_junit_to_allure_surfaces_fio_model_elapsed_in_report(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    allure_dir = tmp_path / "allure-results"
    allure_dir.mkdir()
    fio_line = (
        "FIO command failed, model=randwrite bs=4k qd=64 runtime=30s (#2), "
        "config=2-randwrite-4k-64-30.log, elapsed=12s(12s), planned_runtime=30s, rc=8"
    )
    fio_detail = (
        "----- FIO error detail begin (log=2-randwrite-4k-64-30.log model=randwrite rc=8) -----&#10;"
        "fio: io_u error on file /dev/dp0-vd1: Invalid argument: read offset=0, buflen=1024&#10;"
        "fio: first direct IO errored. File system may not support direct IO, or iomem_align= is bad, "
        "or invalid block size. Try setting direct=0.&#10;"
        "err=22/file:io_u.c:1845, func=io_u error, error=Invalid argument&#10;"
        "----- FIO error detail end (lines=3) -----"
    )
    (tmp_path / "report_192.168.22.134.xml").write_text(
        f"""<?xml version="1.0" encoding="utf-8"?>
<testsuite name="pytest" tests="1" failures="1">
  <testcase classname="test_items.test_smoke_03_lawdisk" name="test_lawdiskstress">
    <failure message="FIO 脚本执行失败，返回码: 8&#10;{fio_line}&#10;{fio_detail}">AssertionError</failure>
  </testcase>
</testsuite>
""",
        encoding="utf-8",
    )

    assert junit_to_allure.main() == 0

    result = json.loads(next(allure_dir.glob("*-result.json")).read_text(encoding="utf-8"))
    assert "model=randwrite bs=4k qd=64 runtime=30s (#2)" in result["statusDetails"]["message"]
    assert "elapsed=12s" in result["statusDetails"]["message"]
    attachment = next(
        item for item in result["attachments"] if item["name"] == "FIO Failure Detail"
    )
    detail_text = (allure_dir / attachment["source"]).read_text(encoding="utf-8")
    assert "elapsed=12s" in detail_text
    assert "io_u error" in detail_text
    assert "Invalid argument" in detail_text
    assert "io_u error" in result["statusDetails"]["trace"]


def test_junit_to_allure_generates_broken_result_for_hung_test_without_junit(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    allure_dir = tmp_path / "allure-results"
    allure_dir.mkdir()
    execution_log = tmp_path / "test_execution_192.168.22.134.log"
    execution_log.write_text(
        "[192.168.22.134] ERROR: idle watchdog fired after 15 minutes, target may be hung.\n"
        "TEST_EXECUTION_STATUS=failed\n"
        "TEST_EXECUTION_EXIT_CODE=124\n",
        encoding="utf-8",
    )

    assert junit_to_allure.main() == 0

    results = [json.loads(path.read_text(encoding="utf-8")) for path in allure_dir.glob("*-result.json")]
    assert len(results) == 1
    result = results[0]
    assert result["name"] == "Test_Execution_Physical_192.168.22.134"
    assert result["status"] == "broken"
    assert "idle watchdog fired" in result["statusDetails"]["message"]
    attachment = allure_dir / result["attachments"][0]["source"]
    assert attachment.read_text(encoding="utf-8") == execution_log.read_text(encoding="utf-8")

    assert junit_to_allure.main() == 0
    assert len(list(allure_dir.glob("*-result.json"))) == 1


def test_junit_to_allure_generates_result_for_aborted_empty_execution_log(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    allure_dir = tmp_path / "allure-results"
    allure_dir.mkdir()
    (tmp_path / "test_execution_192.168.22.134.log").write_text("", encoding="utf-8")
    (tmp_path / "jenkins_console.log").write_text(
        "Running nvme_raid_test.py\nAborted by cyril\nFinished: ABORTED\n",
        encoding="utf-8",
    )

    assert junit_to_allure.main() == 0

    results = [json.loads(path.read_text(encoding="utf-8")) for path in allure_dir.glob("*-result.json")]
    assert len(results) == 1
    result = results[0]
    assert result["name"] == "Test_Execution_Physical_192.168.22.134"
    assert result["status"] == "broken"
    assert "aborted or incomplete" in result["statusDetails"]["message"]
    assert any(item["name"] == "终端输出" for item in result["attachments"])


def test_junit_to_allure_console_fallback_when_no_execution_log(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    allure_dir = tmp_path / "allure-results"
    allure_dir.mkdir()
    (tmp_path / "jenkins_console.log").write_text(
        "Pipeline aborted\nAborted by cyril\nFinished: ABORTED\n",
        encoding="utf-8",
    )

    assert junit_to_allure.main() == 0

    results = [json.loads(path.read_text(encoding="utf-8")) for path in allure_dir.glob("*-result.json")]
    assert len(results) == 1
    result = results[0]
    assert result["name"] == "Test_Execution_Build_Console"
    assert result["status"] == "broken"
    assert "aborted" in result["statusDetails"]["message"].lower()


def test_junit_to_allure_treats_all_node_reports_as_physical(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    allure_dir = tmp_path / "allure-results"
    allure_dir.mkdir()
    junit = """<?xml version="1.0" encoding="utf-8"?>
<testsuite name="pytest" tests="1">
  <testcase classname="test_items.test_smoke_06_basic_io" name="test_basic_io" />
</testsuite>
"""
    (tmp_path / "report_192.168.22.134.xml").write_text(junit, encoding="utf-8")

    assert junit_to_allure.main() == 0

    results = [json.loads(path.read_text(encoding="utf-8")) for path in allure_dir.glob("*-result.json")]
    test_results = [result for result in results if "test_basic_io" in result["name"]]
    assert len(test_results) == 1
    assert {
        label["value"] for label in test_results[0]["labels"] if label["name"] == "target"
    } == {"physical"}
    assert test_results[0]["name"] == "[Physical 192.168.22.134] test_basic_io"

    assert junit_to_allure.main() == 0
    rerun_results = [json.loads(path.read_text(encoding="utf-8")) for path in allure_dir.glob("*-result.json")]
    test_results = [result for result in rerun_results if "test_basic_io" in result["name"]]
    assert len(test_results) == 1


def test_junit_to_allure_dedupes_legacy_physical_suffixed_report(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    allure_dir = tmp_path / "allure-results"
    allure_dir.mkdir()
    junit = """<?xml version="1.0" encoding="utf-8"?>
<testsuite name="pytest" tests="1">
  <testcase classname="test_items.test_smoke_06_basic_io" name="test_basic_io" />
</testsuite>
"""
    (tmp_path / "report_192.168.22.134.xml").write_text(junit, encoding="utf-8")
    (tmp_path / "report_192.168.22.134_physical.xml").write_text(junit, encoding="utf-8")

    assert junit_to_allure.main() == 0

    results = [json.loads(path.read_text(encoding="utf-8")) for path in allure_dir.glob("*-result.json")]
    test_results = [result for result in results if "test_basic_io" in result["name"]]
    assert len(test_results) == 1
    assert test_results[0]["name"] == "[Physical 192.168.22.134] test_basic_io"


def test_junit_to_allure_attaches_pending_monitor_only_to_matching_target(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    allure_dir = tmp_path / "allure-results"
    allure_dir.mkdir()
    other_node_result = {
        "name": "[Physical 192.168.22.125] FIO 测试: lawdiskstress",
        "historyId": "physical:192.168.22.125:test_basic_io",
        "fullName": "physical:192.168.22.125:test_basic_io",
        "testCaseId": "physical:192.168.22.125:test_basic_io",
        "labels": [
            {"name": "host", "value": "192.168.22.125"},
            {"name": "target", "value": "physical"},
        ],
    }
    physical_result = {
        "name": "[Physical 192.168.22.134] FIO 测试: lawdiskstress",
        "historyId": "physical:192.168.22.134:test_basic_io",
        "fullName": "physical:192.168.22.134:test_basic_io",
        "testCaseId": "physical:192.168.22.134:test_basic_io",
        "labels": [
            {"name": "host", "value": "192.168.22.134"},
            {"name": "target", "value": "physical"},
        ],
    }
    (allure_dir / "other-node-result.json").write_text(json.dumps(other_node_result), encoding="utf-8")
    (allure_dir / "physical-result.json").write_text(json.dumps(physical_result), encoding="utf-8")
    (allure_dir / "monitor_attachments.json").write_text(
        json.dumps(
            [
                {
                    "item": "basic_io",
                    "host": "192.168.22.134",
                    "target": "physical",
                    "attachment": {
                        "name": "monitor_log_basic_io",
                        "source": "physical_monitor_log_basic_io.tar.gz",
                        "type": "application/gzip",
                    },
                }
            ]
        ),
        encoding="utf-8",
    )

    assert junit_to_allure.attach_pending_monitor_logs(str(allure_dir)) == 1

    other_node = json.loads((allure_dir / "other-node-result.json").read_text(encoding="utf-8"))
    physical = json.loads((allure_dir / "physical-result.json").read_text(encoding="utf-8"))
    assert "attachments" not in other_node
    assert physical["attachments"][0]["source"] == "physical_monitor_log_basic_io.tar.gz"
