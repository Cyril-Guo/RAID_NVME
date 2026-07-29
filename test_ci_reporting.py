import json
from pathlib import Path

import attach_console_output


def test_console_output_is_attached_to_allure_results(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(attach_console_output, "download_console", lambda: "[Pipeline] running\n")
    allure_dir = tmp_path / "allure-results"
    allure_dir.mkdir()
    result_path = allure_dir / "case-result.json"
    result_path.write_text(
        json.dumps({"name": "test_case", "status": "failed"}),
        encoding="utf-8",
    )

    assert attach_console_output.attach_console() == 1

    result = json.loads(result_path.read_text(encoding="utf-8"))
    attachment = result["attachments"][0]
    assert attachment["name"] == "Jenkins Console Output"
    assert "[Pipeline] running" in (allure_dir / attachment["source"]).read_text(encoding="utf-8")


def test_jenkinsfile_skips_feishu_when_no_testcase_exists():
    source = Path("Jenkinsfile").read_text(encoding="utf-8")

    guard = source.index("if (total == 0)")
    payload = source.index("writeFile file: 'feishu_payload.json'")
    webhook = source.index('curl -s -X POST')

    assert guard < payload < webhook
    assert "no actual test case was executed" in source
    assert "for case in root.findall('.//testcase')" in source
