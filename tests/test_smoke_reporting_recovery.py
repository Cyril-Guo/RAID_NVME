import json
import xml.etree.ElementTree as ET

from ci import junit_to_allure, report_metrics


def _scenario(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "allure-results"
    root.mkdir()
    (tmp_path / "report_192.168.22.134.xml").write_text(
        '<testsuite name="pytest">'
        '<testcase classname="test_items.test_smoke_06_basic_io" name="test_basic_io" />'
        '<testcase classname="test_items.test_smoke_07_basic_rebuild_io" name="test_basic_rebuild_io" />'
        '</testsuite>', encoding="utf-8",
    )
    for number, item in ((6, "basic_io"), (7, "basic_rebuild_io")):
        (root / f"{item}-result.json").write_text(json.dumps({
            "uuid": item, "name": item, "status": "passed",
            "fullName": f"physical:192.168.22.134:test_items.test_smoke_0{number}_{item}#test_{item}",
            "labels": [{"name": "framework", "value": "pytest"},
                       {"name": "host", "value": "192.168.22.134"},
                       {"name": "target", "value": "physical"}],
        }), encoding="utf-8")
    log = tmp_path / "test_execution_192.168.22.134.log"
    log.write_text(
        'TEST_EXECUTION_TARGET=physical\n'
        '[ITEM_START] basic_io\n[ITEM_END] basic_io exit_code=0\n'
        '[ITEM_START] basic_rebuild_io\n[ITEM_END] basic_rebuild_io exit_code=0\n'
        '[ITEM_START] multi_raid_io\n'
        '[PHASE] item=multi_raid_io stage=pytest\n'
        '[CMD_START] dpraid /c0 show vd\n'
        'ERROR: idle watchdog fired after 15 minutes without progress\n'
        'TEST_EXECUTION_STATUS=failed\nTEST_EXECUTION_EXIT_CODE=124\n', encoding="utf-8",
    )
    (tmp_path / "jenkins_console.log").write_text("[Pipeline] start\n" + log.read_text(), encoding="utf-8")
    (tmp_path / "debug_192.168.22.134.log").write_text("fio D io_schedule\n", encoding="utf-8")
    return root


def test_timeout_after_two_passes_is_recovered_once_and_counted(tmp_path, monkeypatch):
    root = _scenario(tmp_path, monkeypatch)
    assert junit_to_allure.main() == 0
    assert junit_to_allure.main() == 0
    results = [json.loads(p.read_text(encoding="utf-8")) for p in root.glob("*-result.json")]
    assert len(results) == 3
    failed = next(r for r in results if r["status"] in ("broken", "failed"))
    assert "multi_raid_io" in failed["name"]
    assert "dpraid /c0 show vd" in failed["statusDetails"]["trace"]
    assert "[Physical 192.168.22.134]" in failed["name"]
    assert [s["name"] for s in failed["steps"][:3]] == ["终端输出", "测试结果", "日志收集"]
    debug = failed["steps"][2]["attachments"]
    assert any("fio D io_schedule" in (root / a["source"]).read_text(encoding="utf-8")
               for a in debug if a["type"] == "text/plain")
    assert report_metrics.report_metrics() == {
        "tests": 3, "failures": 0, "errors": 1, "skipped": 0, "kind": "tests",
    }
    cases = ET.parse("report_192.168.22.134.xml").getroot().findall(".//testcase")
    assert len(cases) == 3


def test_metrics_counts_unreported_timeout_before_allure_conversion(tmp_path, monkeypatch):
    _scenario(tmp_path, monkeypatch)
    stats = report_metrics.report_metrics()
    assert stats["tests"] == 3
    assert stats["errors"] == 1


def test_manual_abort_does_not_create_missing_failed_case(tmp_path, monkeypatch):
    _scenario(tmp_path, monkeypatch)
    from pathlib import Path
    Path("test_execution_192.168.22.134.log").write_text(
        "TEST_EXECUTION_TARGET=physical\n[ITEM_START] multi_raid_io\n", encoding="utf-8",
    )
    Path("jenkins_console.log").write_text("Aborted by Cyril\nFinished: ABORTED\n", encoding="utf-8")
    junit_to_allure.main()
    assert report_metrics.report_metrics()["errors"] == 0


def test_failure_context_does_not_blame_completed_command(tmp_path, monkeypatch):
    from ci.execution_failure import failure_context
    context = failure_context(
        "[ITEM_START] multi_raid_io\n[CMD_START] lsblk\n[CMD_END] rc=0 command=lsblk\n"
        "[PHASE] item=multi_raid_io stage=verify_vd_count\n",
    )
    assert context["item"] == "multi_raid_io"
    assert context["pending_command"] == "unknown"
    assert context["last_command"] == "lsblk"


def test_feishu_lists_recovered_case_and_manual_abort_sends_nothing(tmp_path, monkeypatch):
    from ci import build_feishu_payload
    _scenario(tmp_path, monkeypatch)
    junit_to_allure.main()
    monkeypatch.setenv("TOTAL", "3")
    monkeypatch.setenv("ERRORS", "1")
    build_feishu_payload.main()
    payload = tmp_path / "feishu_payload.json"
    data = json.loads(payload.read_text(encoding="utf-8"))
    assert any("test_multi_raid_io" in e.get("text", {}).get("content", "") for e in data["card"]["elements"])
    (tmp_path / "jenkins_console.log").write_text("Aborted by Cyril\n", encoding="utf-8")
    build_feishu_payload.main()
    assert not payload.exists()


def test_completed_failure_does_not_hide_later_hang(tmp_path, monkeypatch):
    _scenario(tmp_path, monkeypatch)
    path = tmp_path / "report_192.168.22.134.xml"
    root = ET.parse(path).getroot()
    ET.SubElement(root.find("testcase"), "failure", message="earlier error")
    ET.ElementTree(root).write(path)
    assert report_metrics.report_metrics()["errors"] == 1
    junit_to_allure.main()
    assert report_metrics.report_metrics()["tests"] == 3


def test_explicit_manual_abort_never_adds_execution_failure(tmp_path, monkeypatch):
    root = _scenario(tmp_path, monkeypatch)
    (tmp_path / "manual_abort.txt").write_text("true")
    junit_to_allure.main()
    assert len(list(root.glob("*-result.json"))) == 2
    assert report_metrics.report_metrics()["errors"] == 0


def test_recorded_failure_context_is_not_overwritten_by_collection(tmp_path):
    from ci.execution_failure import failure_context
    context = failure_context(
        "[ITEM_START] multi_raid_io\n[CMD_START] dpraid\n"
        "TEST_EXECUTION_STATUS=failed\nTEST_EXECUTION_EXIT_CODE=124\n"
        "[FAILURE_CONTEXT] Last output: [ITEM_END] basic_io exit_code=0\n"
        "[CMD_START] cleanup\n[CMD_END] rc=0 command=cleanup\n",
    )
    assert context["item"] == "multi_raid_io"
    assert context["pending_command"] == "dpraid"
    assert context["exit_code"] == "124"


def test_collection_hang_is_infra_not_a_failed_passed_case():
    from ci.execution_failure import failure_context
    context = failure_context(
        "[ITEM_START] basic_io\n[CMD_START] lsblk\n[CMD_END] rc=0 command=lsblk\n"
        "[ITEM_END] basic_io exit_code=0\n[PHASE] item=basic_io stage=log_collection\n",
    )
    assert context["item"] == "unknown"
    assert context["last_item"] == "basic_io"
    assert context["pending_command"] == "unknown"


def test_pre_pytest_exception_keeps_failed_item_after_cleanup(tmp_path, monkeypatch):
    from ci.execution_failure import failure_context
    context = failure_context(
        "[ITEM_START] multi_raid_io\n[PHASE] item=multi_raid_io stage=csd_refresh\n"
        "[CMD_START] insmod draid.ko\n[CMD_END] rc=1 command=insmod draid.ko\n"
        "[ITEM_FAILED] multi_raid_io error=AssertionError: Command failed\n"
        "[PHASE] item=multi_raid_io stage=log_collection\n"
        "[ITEM_END] multi_raid_io exit_code=2 collected=yes\n"
        "TEST_EXECUTION_STATUS=failed\nTEST_EXECUTION_EXIT_CODE=1\n",
    )
    assert context["item"] == "multi_raid_io"
    assert context["phase"] == "csd_refresh"
    assert context["last_command"] == "insmod draid.ko"


def test_pytest_nonzero_without_report_keeps_case_identity():
    from ci.execution_failure import failure_context
    context = failure_context(
        "[ITEM_START] mix\n[PHASE] item=mix stage=pytest\n"
        "[ITEM_END] mix exit_code=2\n[PHASE] item=mix stage=log_collection\n"
        "[ITEM_END] mix exit_code=2 collected=yes\n",
    )
    assert context["item"] == "mix"
