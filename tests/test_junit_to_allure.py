import json

from ci import junit_to_allure


def test_junit_to_allure_generates_case_and_attaches_monitor(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    allure_dir = tmp_path / "allure-results"
    allure_dir.mkdir()
    (tmp_path / "report_lawdisk.xml").write_text(
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
    assert result["name"] == "test_lawdiskstress"
    assert result["attachments"][0]["source"] == "monitor_log_lawdisk.tar.gz"

    assert junit_to_allure.main() == 0
    assert len(list(allure_dir.glob("*-result.json"))) == 1
