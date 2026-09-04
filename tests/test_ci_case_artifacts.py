import json
import tarfile


def test_case_logs_survive_missing_pytest_finalization(tmp_path):
    from ci.case_artifacts import recover_case_outputs
    case = tmp_path / "cases" / "mix__2"
    logs = case / "IO_Stress" / "log" / "ResultLog"
    logs.mkdir(parents=True)
    (logs / "result.log").write_text("FIO stage failed\n")
    (case / "fio_command_output_mix__2.log").write_text("watchdog timeout\n")
    (case / "report_mix__2.xml").write_text('<testsuite><testcase name="test_mix_stress" /></testsuite>')
    recover_case_outputs(tmp_path)
    root = tmp_path / "allure-results"
    index = json.loads((root / "case_mix__2_monitor_attachments.json").read_text(encoding="utf-8"))
    assert index[0]["run_key"] == "mix__2"
    with tarfile.open(root / index[0]["attachment"]["source"]) as archive:
        assert "IO_Stress/log/ResultLog/result.log" in archive.getnames()
        assert "fio_command_output_mix__2.log" in archive.getnames()
    assert (tmp_path / "report_mix__2.xml").exists()


def test_case_sidecars_do_not_overwrite_each_other(tmp_path):
    from ci.case_artifacts import recover_case_outputs
    for key in ("mix__2", "mix__5"):
        root = tmp_path / "cases" / key / "allure-results"
        root.mkdir(parents=True)
        (root / "monitor_attachments.json").write_text(json.dumps([
            {"item": "mix", "attachment": {"name": key, "source": f"monitor_{key}.tar.gz"}}]))
        (root / f"monitor_{key}.tar.gz").write_bytes(b"monitor")
    recover_case_outputs(tmp_path)
    root = tmp_path / "allure-results"
    for key in ("mix__2", "mix__5"):
        entries = json.loads((root / f"{key}_monitor_attachments.json").read_text())
        assert entries[0]["run_key"] == key


def test_downloaded_fallback_bundle_attaches_to_matching_case(tmp_path, monkeypatch):
    from ci import junit_to_allure
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "allure-results"
    root.mkdir()
    for key in ("mix__2", "random_io__5"):
        (root / f"{key}-result.json").write_text(json.dumps({"uuid": key, "name": key,
            "status": "failed", "labels": [{"name": "framework", "value": "pytest"},
            {"name": "host", "value": "192.168.22.134"}, {"name": "run_key", "value": key}]}))
    (tmp_path / "test_execution_192.168.22.134.log").write_text("[ITEM_START] mix__2\n[ITEM_END] mix__2 exit_code=1\n")
    bundle = tmp_path / "failure_bundle_192.168.22.134_remote_runner_20260903_204500_1234_5678.tar.gz"
    bundle.write_bytes(b"copied gcore archive")
    junit_to_allure.main()
    for key in ("mix__2", "random_io__5"):
        result = json.loads((root / f"{key}-result.json").read_text(encoding="utf-8"))
        logs = next(s for s in result["steps"] if s["name"] == "日志收集")["attachments"]
        archives = [a for a in logs if a.get("type") == "application/gzip"]
        assert bool(archives) == (key == "mix__2")
        for attachment in archives:
            assert (root / attachment["source"]).read_bytes() == b"copied gcore archive"


def test_case_archive_is_bounded_and_records_truncation(tmp_path, monkeypatch):
    from ci import case_artifacts
    case = tmp_path / "cases" / "mix__2"
    case.mkdir(parents=True)
    (case / "fio.log").write_bytes(b"0123456789")
    monkeypatch.setattr(case_artifacts, "MAX_FILE_BYTES", 4)
    case_artifacts.recover_case_outputs(tmp_path)
    with tarfile.open(tmp_path / "allure-results" / "case_debug_mix__2.tar.gz") as archive:
        assert archive.extractfile("fio.log").read() == b"6789"
        assert b"tail_only=True" in archive.extractfile("collection_manifest.txt").read()


def test_recovery_repairs_partial_json_without_overwriting_completed_results(tmp_path):
    from ci.case_artifacts import recover_case_outputs
    source = tmp_path / "cases" / "mix__2" / "allure-results"
    source.mkdir(parents=True)
    root = tmp_path / "allure-results"
    root.mkdir()
    (source / "partial-result.json").write_text('{"uuid": "partial"}')
    (root / "partial-result.json").write_text('{"uuid":')
    (source / "complete-result.json").write_text('{"uuid": "complete"}')
    (root / "complete-result.json").write_text('{"uuid": "complete", "attachments": ["keep"]}')
    recover_case_outputs(tmp_path)
    assert json.loads((root / "partial-result.json").read_text())["uuid"] == "partial"
    assert json.loads((root / "complete-result.json").read_text())["attachments"] == ["keep"]


def test_collection_after_success_has_no_false_case_attribution(tmp_path):
    from ci.report_artifacts import last_run
    log = tmp_path / "node.log"
    log.write_text("[ITEM_START] mix__2\n[ITEM_END] mix__2 exit_code=0\n")
    assert last_run(log) == ""
    log.write_text("[ITEM_START] mix__2\n[ITEM_END] mix__2 exit_code=0\n[ITEM_START] random_io__5\n")
    assert last_run(log) == "random_io__5"


def test_interrupted_case_logs_attach_to_execution_failure_without_junit(tmp_path, monkeypatch):
    from ci import junit_to_allure, mark_allure_target_context
    from ci.case_artifacts import recover_case_outputs
    monkeypatch.chdir(tmp_path)
    case = tmp_path / "cases" / "mix__2"
    case.mkdir(parents=True)
    (case / "fio.log").write_text("watchdog interrupted the runner")
    recover_case_outputs(tmp_path)
    root = tmp_path / "allure-results"
    mark_allure_target_context.main([str(root), "192.168.22.134"])
    (tmp_path / "test_execution_192.168.22.134.log").write_text(
        "[ITEM_START] mix__2\nidle watchdog fired\nTEST_EXECUTION_STATUS=failed\n")
    junit_to_allure.main()
    results = list(root.glob("*-result.json"))
    assert len(results) == 1
    result = json.loads(results[0].read_text(encoding="utf-8"))
    assert result["status"] == "broken"
    logs = next(s for s in result["steps"] if s["name"] == "日志收集")["attachments"]
    assert any(a["source"].endswith("case_debug_mix__2.tar.gz") for a in logs)
