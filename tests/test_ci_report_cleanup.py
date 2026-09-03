import json

from ci import junit_to_allure, mark_allure_target_context


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def result(run="mix__2", node="192.168.22.134", status="failed"):
    return {
        "uuid": f"{node}-{run}", "name": "FIO mix", "status": status,
        "fullName": f"physical:{node}:{run}::test_items.test_ci_05_mix#test_mix_stress",
        "labels": [{"name": "host", "value": node}, {"name": "target", "value": "physical"},
                   {"name": "run_key", "value": run}, {"name": "framework", "value": "pytest"},
                   {"name": "parentSuite", "value": "测试日志"}, {"name": "suite", "value": run}],
    }


def sections(data):
    return {s["name"]: s for s in data["steps"]}


def test_nested_logs_and_fixture_errors_move_to_three_sections(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "allure-results"
    root.mkdir()
    data = result(status="passed")
    data["steps"] = [{"name": "FIO", "attachments": [
        {"name": "FIO 执行日志", "source": "fio.txt", "type": "text/plain"}]}]
    write_json(root / "mix-result.json", data)
    (root / "fio.txt").write_text("FIO command log")
    (root / "fixture.txt").write_text("cleanup debug")
    write_json(root / "fixture-container.json", {"uuid": "fixture", "children": [data["uuid"]],
        "befores": [{"name": "raid_nvme_run_context", "status": "passed"}],
        "afters": [{"name": "cleanup", "status": "broken", "statusDetails": {
            "message": "cleanup failed", "trace": "cleanup traceback"}, "attachments": [
                {"name": "cleanup stdout", "source": "fixture.txt", "type": "text/plain"}]}]})
    mark_allure_target_context.main([str(root), "192.168.22.134"])
    junit_to_allure.main()
    junit_to_allure.main()
    saved = json.loads((root / "mix-result.json").read_text(encoding="utf-8"))
    assert [s["name"] for s in saved["steps"]] == ["终端输出", "测试结果", "日志收集"]
    assert saved["status"] == "broken"
    grouped = sections(saved)
    assert any("cleanup failed" in (root / a["source"]).read_text(encoding="utf-8")
               for a in grouped["测试结果"]["attachments"])
    logs = grouped["日志收集"]["attachments"]
    assert {"FIO 执行日志", "cleanup stdout"} <= {a["name"] for a in logs}
    assert all((root / a["source"]).is_file() for a in logs)
    container = json.loads((root / "fixture-container.json").read_text())
    assert not container.get("befores") and not container.get("afters")


def test_pytest_duplicates_removed_but_real_internal_error_preserved(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "allure-results"
    root.mkdir()
    write_json(root / "native-result.json", result())
    duplicate = result()
    duplicate.update(uuid="converted", fullName="physical:192.168.22.134:test_items.mix__2#test_mix_stress")
    duplicate["labels"] = [l for l in duplicate["labels"] if l["name"] not in ("parentSuite", "suite")]
    duplicate["labels"].append({"name": "suite", "value": "pytest"})
    write_json(root / "duplicate-result.json", duplicate)
    for name, status in (("unknown", "passed"), ("internal", "broken")):
        write_json(root / f"{name}-result.json", {"uuid": name, "name": f"[Physical 192.168.22.134] {name}",
            "status": status, "labels": [{"name": "host", "value": "192.168.22.134"},
            {"name": "framework", "value": "pytest"}, {"name": "suite", "value": "pytest"}],
            "statusDetails": {"message": "pytest plugin crashed" if status == "broken" else ""}})
    junit_to_allure.main()
    junit_to_allure.main()
    results = [json.loads(p.read_text(encoding="utf-8")) for p in root.glob("*-result.json")]
    assert len(results) == 2  # Real case + independent framework failure, not false green unknown.
    assert all(not any(l.get("value") == "pytest" for l in r["labels"]
                      if l.get("name") in ("parentSuite", "suite", "subSuite")) for r in results)
    assert any("pytest plugin crashed" in r.get("statusDetails", {}).get("message", "") for r in results)


def test_native_case_does_not_suppress_another_junit_case(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "allure-results"
    root.mkdir()
    write_json(root / "native-result.json", result())
    (tmp_path / "report_192.168.22.134.xml").write_text(
        '<testsuite name="pytest"><testcase classname="test_items.mix__2" name="test_mix_stress">'
        '<failure message="fio timeout" /></testcase>'
        '<testcase classname="test_items.random_io__5" name="test_random_io" /></testsuite>')
    junit_to_allure.main()
    results = [json.loads(p.read_text(encoding="utf-8")) for p in root.glob("*-result.json")]
    assert len(results) == 2
    assert any("random_io" in r["name"] for r in results)


def test_sidecars_match_exact_host_and_run_key(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "allure-results"
    root.mkdir()
    for run in ("mix__2", "mix__5"):
        for node in ("192.168.22.134", "192.168.22.135"):
            write_json(root / f"{node}-{run}-result.json", result(run, node))
    (root / "case.tar.gz").write_bytes(b"debug")
    write_json(root / "physical_134_monitor_attachments.json", [{"item": "mix", "run_key": "mix__2",
        "host": "192.168.22.134", "target": "physical", "attachment": {
        "name": "case debug", "source": "case.tar.gz", "type": "application/gzip"}}])
    junit_to_allure.main()
    for path in root.glob("*-result.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        found = any(a["source"] == "case.tar.gz" for a in sections(data)["日志收集"]["attachments"])
        assert found == (path.name == "192.168.22.134-mix__2-result.json")


def test_missing_attachment_has_explanation_not_dead_link(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "allure-results"
    root.mkdir()
    data = result()
    data["attachments"] = [{"name": "missing bundle", "source": "not_copied.tar.gz", "type": "application/gzip"}]
    write_json(root / "mix-result.json", data)
    junit_to_allure.main()
    saved = json.loads((root / "mix-result.json").read_text(encoding="utf-8"))
    debug = sections(saved)["日志收集"]["attachments"]
    assert all((root / a["source"]).exists() for a in debug)
    explanation = next(a for a in debug if a["name"] == "附件缺失说明")
    assert "not_copied.tar.gz" in (root / explanation["source"]).read_text(encoding="utf-8")


def test_two_nodes_with_same_case_keep_separate_log_content(tmp_path, monkeypatch):
    import shutil
    from ci.case_artifacts import recover_case_outputs
    monkeypatch.chdir(tmp_path)
    destination = tmp_path / "allure-results"
    destination.mkdir()
    for node in ("192.168.22.134", "192.168.22.135"):
        workspace = tmp_path / node
        case = workspace / "cases" / "mix__2"
        raw = case / "allure-results"
        raw.mkdir(parents=True)
        (case / "fio.log").write_text(node)
        write_json(raw / f"{node}-result.json", result(node=node))
        recover_case_outputs(workspace)
        landed = workspace / "allure-results"
        mark_allure_target_context.main([str(landed), node])
        mark_allure_target_context.main([str(landed), node])
        shutil.copytree(landed, destination, dirs_exist_ok=True)
    junit_to_allure.main()
    junit_to_allure.main()
    import tarfile
    for path in destination.glob("*-result.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        node = next(l["value"] for l in data["labels"] if l["name"] == "host")
        attachments = sections(data)["日志收集"]["attachments"]
        assert len(attachments) == 1
        with tarfile.open(destination / attachments[0]["source"]) as archive:
            assert archive.extractfile("fio.log").read().decode() == node
