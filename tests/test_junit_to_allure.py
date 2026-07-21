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


def test_junit_to_allure_keeps_qemu_and_physical_results(tmp_path, monkeypatch):
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
    assert len(test_results) == 2
    assert {
        next(label["value"] for label in result["labels"] if label["name"] == "target")
        for result in test_results
    } == {"qemu", "physical"}
    assert {result["name"] for result in test_results} == {
        "[QEMU 192.168.22.134] test_basic_io",
        "[Physical 192.168.22.134] test_basic_io",
    }

    assert junit_to_allure.main() == 0
    rerun_results = [json.loads(path.read_text(encoding="utf-8")) for path in allure_dir.glob("*-result.json")]
    test_results = [result for result in rerun_results if "test_basic_io" in result["name"]]
    assert len(test_results) == 2
