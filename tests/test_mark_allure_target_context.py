import json

from ci import mark_allure_target_context


def write_result(path, name, history_id, attachment_source):
    path.write_text(
        json.dumps(
            {
                "name": name,
                "fullName": f"tests#{name}",
                "historyId": history_id,
                "testCaseId": history_id,
                "labels": [{"name": "suite", "value": "test_ci_05_mix_4k"}],
                "attachments": [
                    {
                        "name": "monitor_log_test_ci_05_mix_4k",
                        "source": attachment_source,
                        "type": "application/gzip",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_mark_allure_target_context_marks_physical_history_and_attachments(tmp_path):
    allure_dir = tmp_path / "physical"
    allure_dir.mkdir()
    write_result(allure_dir / "physical-result.json", "FIO test: lawdiskstress", "same-history", "monitor_log_test_ci_05_mix_4k.tar.gz")
    (allure_dir / "monitor_log_test_ci_05_mix_4k.tar.gz").write_bytes(b"physical")

    assert mark_allure_target_context.main([str(allure_dir), "192.168.22.134"]) == 0

    physical = json.loads((allure_dir / "physical-result.json").read_text(encoding="utf-8"))

    assert physical["name"] == "[Physical 192.168.22.134] FIO test: lawdiskstress"
    assert {label["value"] for label in physical["labels"] if label["name"] == "target"} == {"physical"}
    assert physical["attachments"][0]["source"] == "physical_192_168_22_134_monitor_log_test_ci_05_mix_4k.tar.gz"
    assert (allure_dir / physical["attachments"][0]["source"]).read_bytes() == b"physical"


def test_mark_allure_target_context_marks_pending_monitor_sidecar(tmp_path):
    allure_dir = tmp_path / "allure"
    allure_dir.mkdir()
    (allure_dir / "monitor_log_test_ci_05_mix_4k.tar.gz").write_bytes(b"log")
    (allure_dir / "monitor_attachments.json").write_text(
        json.dumps(
            [
                {
                    "item": "test_ci_05_mix_4k",
                    "attachment": {
                        "name": "monitor_log_test_ci_05_mix_4k",
                        "source": "monitor_log_test_ci_05_mix_4k.tar.gz",
                        "type": "application/gzip",
                    },
                }
            ]
        ),
        encoding="utf-8",
    )

    assert mark_allure_target_context.main([str(allure_dir), "192.168.22.134"]) == 0

    pending = json.loads((allure_dir / "physical_192_168_22_134_monitor_attachments.json").read_text(encoding="utf-8"))
    assert pending[0]["item"] == "test_ci_05_mix_4k"
    assert pending[0]["host"] == "192.168.22.134"
    assert pending[0]["target"] == "physical"
    assert pending[0]["attachment"]["source"] == "physical_192_168_22_134_monitor_log_test_ci_05_mix_4k.tar.gz"
