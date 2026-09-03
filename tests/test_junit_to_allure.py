import json

from ci import junit_to_allure


def _section(result, name):
    return next(step for step in result["steps"] if step["name"] == name)


def test_junit_to_allure_generates_case_and_attaches_monitor(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    allure_dir = tmp_path / "allure-results"
    allure_dir.mkdir()
    (allure_dir / "monitor_log_lawdisk.tar.gz").write_bytes(b"monitor archive")
    (tmp_path / "report_192.168.22.134.xml").write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<testsuite name="pytest" tests="1">
  <testcase classname="test_items.test_ci_03_lawdisk" name="test_lawdiskstress" />
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
    assert "start" in result and "stop" in result
    assert result["stop"] >= result["start"]
    debug = _section(result, "日志收集")
    assert debug["attachments"][0]["source"] == "monitor_log_lawdisk.tar.gz"

    assert junit_to_allure.main() == 0
    assert len(list(allure_dir.glob("*-result.json"))) == 1


def test_junit_to_allure_skips_node_junit_when_pytest_allure_exists(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    allure_dir = tmp_path / "allure-results"
    allure_dir.mkdir()
    existing_uuid = "11111111-1111-1111-1111-111111111111"
    (allure_dir / f"{existing_uuid}-result.json").write_text(
        json.dumps(
            {
                "uuid": existing_uuid,
                "name": "[Physical 192.168.22.134] test_lawdiskstress",
                "status": "passed",
                "stage": "finished",
                "start": 1_700_000_000_000,
                "stop": 1_700_000_123_000,
                "labels": [
                    {"name": "framework", "value": "pytest"},
                    {"name": "host", "value": "192.168.22.134"},
                    {"name": "run_key", "value": "lawdisk__2"},
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "report_192.168.22.134.xml").write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<testsuite name="pytest" tests="1">
  <testcase classname="test_items.lawdisk__2" name="test_lawdiskstress" time="12.5" />
</testsuite>
""",
        encoding="utf-8",
    )

    assert junit_to_allure.main() == 0
    assert len(list(allure_dir.glob("*-result.json"))) == 1


def test_junit_to_allure_attaches_console_snapshot(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BUILD_URL", "http://jenkins/job/SMOKE/12/")
    allure_dir = tmp_path / "allure-results"
    allure_dir.mkdir()
    (tmp_path / "report_192.168.22.134.xml").write_text(
        """<testsuite name="pytest">
  <testcase classname="test_items.test_ci" name="test_basic_io" />
</testsuite>
""",
        encoding="utf-8",
    )
    (tmp_path / "jenkins_console.log").write_text(
        "[Pipeline] stage\n"
        "[ITEM_START] basic_io\n"
        "[ITEM] basic_io -> test_items/test_ci_06_basic_io.py\n"
        "all console output\n"
        "[ITEM_END] basic_io exit_code=0\n"
        "[Pipeline] echo\n",
        encoding="utf-8",
    )

    assert junit_to_allure.main() == 0

    result_path = next(allure_dir.glob("*-result.json"))
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert [step["name"] for step in result["steps"][:3]] == ["终端输出", "测试结果", "日志收集"]
    console_attachment = _section(result, "终端输出")["attachments"][0]
    assert console_attachment["name"] == "完整 Jenkins Console"
    console_text = (allure_dir / console_attachment["source"]).read_text(encoding="utf-8")
    assert "all console output" in console_text
    assert "[Pipeline] stage" in console_text
    assert "[Pipeline] echo" in console_text
    assert "links" not in result


def test_junit_to_allure_large_console_remains_one_complete_attachment(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    allure_dir = tmp_path / "allure-results"
    allure_dir.mkdir()
    (tmp_path / "report_192.168.22.134.xml").write_text(
        """<testsuite name="pytest">
  <testcase classname="test_items.test_ci" name="test_basic_io" />
</testsuite>
""",
        encoding="utf-8",
    )
    (tmp_path / "jenkins_console.log").write_text(
        "[ITEM_START] basic_io\n" + ("x" * (1024 * 1024 + 8)) + "\n[ITEM_END] basic_io exit_code=0\n",
        encoding="utf-8",
    )

    assert junit_to_allure.main() == 0

    result = json.loads(next(allure_dir.glob("*-result.json")).read_text(encoding="utf-8"))
    attachments = _section(result, "终端输出")["attachments"]
    assert len(attachments) == 1
    assert attachments[0]["name"] == "完整 Jenkins Console"
    assert (allure_dir / attachments[0]["source"]).stat().st_size > 1024 * 1024



def test_junit_to_allure_does_not_copy_global_fio_summary_onto_every_case(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    allure_dir = tmp_path / "allure-results"
    allure_dir.mkdir()
    (tmp_path / "report_192.168.23.94.xml").write_text(
        """<testsuites>
  <testsuite name="pytest">
    <testcase classname="test_items.test_ci_05_mix" name="test_mix_stress" />
    <testcase classname="test_items.test_ci_06_basic_io" name="test_basic_io" />
  </testsuite>
</testsuites>
""",
        encoding="utf-8",
    )
    (tmp_path / "test_execution_192.168.23.94.log").write_text(
        "[ITEM_START] mix\n"
        "mix only line\n"
        "Job 1/2800 is Running..\n"
        "[ITEM_END] mix exit_code=0\n"
        "[ITEM_START] basic_io\n"
        "basic io only line\n"
        "[ITEM_END] basic_io exit_code=0\n",
        encoding="utf-8",
    )
    (tmp_path / "jenkins_console.log").write_text(
        "all cases share this console\nJob 2800/2800 is Running..\n",
        encoding="utf-8",
    )

    assert junit_to_allure.main() == 0

    results = [json.loads(path.read_text(encoding="utf-8")) for path in allure_dir.glob("*-result.json")]
    assert len(results) == 2
    by_name = {result["name"]: result for result in results}
    mix = by_name["[Physical 192.168.23.94] test_mix_stress"]
    basic = by_name["[Physical 192.168.23.94] test_basic_io"]
    for result in results:
        names = [item["name"] for item in _section(result, "测试结果")["attachments"]]
        assert "FIO 任务摘要" not in names
        assert "测试结果汇总" not in names
        assert "MachineCheck 差异记录" not in names
        assert "执行结果" in names
    mix_console = _section(mix, "终端输出")["attachments"][0]
    basic_console = _section(basic, "终端输出")["attachments"][0]
    mix_text = (allure_dir / mix_console["source"]).read_text(encoding="utf-8")
    basic_text = (allure_dir / basic_console["source"]).read_text(encoding="utf-8")
    assert mix_text == basic_text
    assert "all cases share this console" in mix_text


def test_junit_to_allure_copies_full_jenkins_console_onto_pytest_case(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    allure_dir = tmp_path / "allure-results"
    allure_dir.mkdir()
    (tmp_path / "report_192.168.22.134.xml").write_text(
        """<testsuite name="pytest">
  <testcase classname="test_items.test_ci_05_mix" name="test_mix_stress" />
</testsuite>
""",
        encoding="utf-8",
    )
    (tmp_path / "jenkins_console.log").write_text(
        "[Pipeline] stage\nthis is the full Jenkins console\n",
        encoding="utf-8",
    )

    assert junit_to_allure.main() == 0

    result = json.loads(next(allure_dir.glob("*-result.json")).read_text(encoding="utf-8"))
    console = _section(result, "终端输出")["attachments"][0]
    assert console["name"] == "完整 Jenkins Console"
    assert "this is the full Jenkins console" in (
        allure_dir / console["source"]
    ).read_text(encoding="utf-8")


def test_junit_to_allure_relabels_existing_pytest_terminal_as_debug_log(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    allure_dir = tmp_path / "allure-results"
    allure_dir.mkdir()
    source = "case-terminal.log"
    (allure_dir / source).write_text("this case stdout only\n", encoding="utf-8")
    result = {
        "name": "FIO 测试: mix (混合 IO)",
        "historyId": "192.168.23.94::physical::test_items.test_ci_05_mix::test_mix_stress",
        "fullName": "physical:192.168.23.94:test_items.test_ci_05_mix#test_mix_stress",
        "testCaseId": "192.168.23.94::physical::test_items.test_ci_05_mix::test_mix_stress",
        "labels": [
            {"name": "package", "value": "test_items.test_ci_05_mix"},
            {"name": "framework", "value": "pytest"},
        ],
        "attachments": [{"name": "终端输出", "source": source, "type": "text/plain"}],
    }
    (allure_dir / "pytest-mix-result.json").write_text(json.dumps(result), encoding="utf-8")
    (tmp_path / "report_192.168.23.94.xml").write_text(
        """<testsuite name="pytest">
  <testcase classname="test_items.test_ci_05_mix" name="test_mix_stress" />
</testsuite>
""",
        encoding="utf-8",
    )
    (tmp_path / "jenkins_console.log").write_text(
        "[ITEM_START] mix\njenkins slice for mix\n[ITEM_END] mix exit_code=0\n",
        encoding="utf-8",
    )

    assert junit_to_allure.main() == 0

    saved = json.loads((allure_dir / "pytest-mix-result.json").read_text(encoding="utf-8"))
    console = _section(saved, "终端输出")["attachments"][0]
    assert console["name"] == "完整 Jenkins Console"
    debug = next(
        item
        for item in _section(saved, "日志收集")["attachments"]
        if item["name"] == "FIO 执行日志（旧版）"
    )
    assert (allure_dir / debug["source"]).read_text(encoding="utf-8") == "this case stdout only\n"


def test_junit_to_allure_groups_console_result_and_debug_logs_as_siblings(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    allure_dir = tmp_path / "allure-results"
    allure_dir.mkdir()
    (tmp_path / "jenkins_console.log").write_text(
        "[Pipeline] Start of Pipeline\nfull Jenkins console\n[Pipeline] End of Pipeline\n",
        encoding="utf-8",
    )
    (allure_dir / "fio.log").write_text("fio raw output\n", encoding="utf-8")
    (allure_dir / "failure.txt").write_text("primary_error=Input/output error\n", encoding="utf-8")
    (allure_dir / "failure_bundle.tar.gz").write_bytes(b"debug bundle")
    result = {
        "uuid": "case-uuid",
        "name": "FIO 测试: mix (混合 IO)",
        "status": "failed",
        "stage": "finished",
        "statusDetails": {
            "message": "FIO 脚本执行失败",
            "trace": "primary_error=Input/output error",
        },
        "labels": [{"name": "framework", "value": "pytest"}],
        "attachments": [
            {"name": "FIO 执行日志", "source": "fio.log", "type": "text/plain"},
            {"name": "FIO 故障摘要", "source": "failure.txt", "type": "text/plain"},
            {
                "name": "failure_gcore_bundle_mix",
                "source": "failure_bundle.tar.gz",
                "type": "application/gzip",
            },
        ],
    }
    result_path = allure_dir / "case-result.json"
    result_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")

    assert junit_to_allure.main() == 0
    assert junit_to_allure.main() == 0

    saved = json.loads(result_path.read_text(encoding="utf-8"))
    assert "attachments" not in saved
    assert [step["name"] for step in saved["steps"][:3]] == ["终端输出", "测试结果", "日志收集"]
    terminal = _section(saved, "终端输出")["attachments"]
    assert [item["name"] for item in terminal] == ["完整 Jenkins Console"]
    assert "full Jenkins console" in (allure_dir / terminal[0]["source"]).read_text(encoding="utf-8")
    result_names = [item["name"] for item in _section(saved, "测试结果")["attachments"]]
    assert result_names == ["报错日志", "FIO 故障摘要"]
    debug_names = [item["name"] for item in _section(saved, "日志收集")["attachments"]]
    assert debug_names == ["FIO 执行日志", "failure_gcore_bundle_mix"]


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
    attachment = allure_dir / _section(env_result, "日志收集")["attachments"][0]["source"]
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
  <testcase classname="test_items.test_ci_03_lawdisk" name="test_lawdiskstress" />
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
  <testcase classname="test_items.test_ci_03_lawdisk" name="test_lawdiskstress">
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
        item
        for item in _section(result, "测试结果")["attachments"]
        if item["name"] == "FIO Failure Detail"
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
    attachment = allure_dir / _section(result, "日志收集")["attachments"][0]["source"]
    assert attachment.read_text(encoding="utf-8") == execution_log.read_text(encoding="utf-8")

    assert junit_to_allure.main() == 0
    assert len(list(allure_dir.glob("*-result.json"))) == 1


def test_junit_to_allure_generates_execution_result_when_junit_only_passed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    allure_dir = tmp_path / "allure-results"
    allure_dir.mkdir()
    (tmp_path / "report_192.168.22.134.xml").write_text(
        """<testsuite name="pytest">
  <testcase classname="test_items.test_ci_05_mix" name="test_mix_stress" />
</testsuite>
""",
        encoding="utf-8",
    )
    execution_log = tmp_path / "test_execution_192.168.22.134.log"
    execution_log.write_text(
        "FIO command failed in MIX mode job 10, model=rw bs=4k qd=32 runtime=30s (#10), elapsed=1s, rc=96/96/96/96\n"
        "TEST_EXECUTION_STATUS=failed\n"
        "TEST_EXECUTION_EXIT_CODE=1\n",
        encoding="utf-8",
    )

    assert junit_to_allure.main() == 0

    results = [json.loads(path.read_text(encoding="utf-8")) for path in allure_dir.glob("*-result.json")]
    names = {result["name"] for result in results}
    assert "[Physical 192.168.22.134] test_mix_stress" in names
    assert "Test_Execution_Physical_192.168.22.134" in names


def test_junit_to_allure_does_not_fail_manually_aborted_empty_execution_log(tmp_path, monkeypatch):
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
    assert results == []


def test_junit_to_allure_still_fails_incomplete_execution_without_manual_abort(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    allure_dir = tmp_path / "allure-results"
    allure_dir.mkdir()
    (tmp_path / "test_execution_192.168.22.134.log").write_text("", encoding="utf-8")

    assert junit_to_allure.main() == 0

    results = [json.loads(path.read_text(encoding="utf-8")) for path in allure_dir.glob("*-result.json")]
    assert len(results) == 1
    assert results[0]["name"] == "Test_Execution_Physical_192.168.22.134"
    assert results[0]["status"] == "broken"


def test_junit_to_allure_keeps_real_failure_before_manual_abort(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    allure_dir = tmp_path / "allure-results"
    allure_dir.mkdir()
    (tmp_path / "test_execution_192.168.22.134.log").write_text(
        "idle watchdog fired after 15 minutes without progress\n"
        "TEST_EXECUTION_STATUS=failed\n",
        encoding="utf-8",
    )
    (tmp_path / "jenkins_console.log").write_text("Aborted by cyril\n", encoding="utf-8")

    assert junit_to_allure.main() == 0

    results = [json.loads(path.read_text(encoding="utf-8")) for path in allure_dir.glob("*-result.json")]
    assert len(results) == 1
    assert results[0]["status"] == "broken"


def test_junit_to_allure_skips_console_fallback_for_manual_abort(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    allure_dir = tmp_path / "allure-results"
    allure_dir.mkdir()
    (tmp_path / "jenkins_console.log").write_text(
        "Pipeline aborted\nAborted by cyril\nFinished: ABORTED\n",
        encoding="utf-8",
    )

    assert junit_to_allure.main() == 0

    results = [json.loads(path.read_text(encoding="utf-8")) for path in allure_dir.glob("*-result.json")]
    assert results == []


def test_junit_to_allure_treats_all_node_reports_as_physical(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    allure_dir = tmp_path / "allure-results"
    allure_dir.mkdir()
    junit = """<?xml version="1.0" encoding="utf-8"?>
<testsuite name="pytest" tests="1">
  <testcase classname="test_items.test_ci_06_basic_io" name="test_basic_io" />
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
  <testcase classname="test_items.test_ci_06_basic_io" name="test_basic_io" />
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
