import json

from powercycle import mark_allure_target_context


def write_result(path, name, history_id, attachment_source):
    path.write_text(
        json.dumps(
            {
                "name": name,
                "fullName": f"tests#{name}",
                "historyId": history_id,
                "testCaseId": history_id,
                "labels": [{"name": "suite", "value": "test_powercycle_00_env_prepare"}],
                "attachments": [
                    {
                        "name": "case_log_env_prepare",
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
    write_result(allure_dir / "physical-result.json", "FIO test: reboot", "same-history", "case_log_env_prepare.tar.gz")
    (allure_dir / "case_log_env_prepare.tar.gz").write_bytes(b"physical")

    assert mark_allure_target_context.main([str(allure_dir), "192.168.22.134"]) == 0

    physical = json.loads((allure_dir / "physical-result.json").read_text(encoding="utf-8"))

    assert physical["name"] == "[Physical 192.168.22.134] FIO test: reboot"
    assert {label["value"] for label in physical["labels"] if label["name"] == "target"} == {"physical"}
    assert physical["attachments"][0]["source"] == "physical_192_168_22_134_case_log_env_prepare.tar.gz"
    assert (allure_dir / physical["attachments"][0]["source"]).read_bytes() == b"physical"


def test_mark_allure_target_context_marks_pending_monitor_sidecar(tmp_path):
    allure_dir = tmp_path / "allure"
    allure_dir.mkdir()
    (allure_dir / "case_log_env_prepare.tar.gz").write_bytes(b"log")
    (allure_dir / "case_attachments.json").write_text(
        json.dumps(
            [
                {
                    "item": "basic_io",
                    "attachment": {
                        "name": "case_log_env_prepare",
                        "source": "case_log_env_prepare.tar.gz",
                        "type": "application/gzip",
                    },
                }
            ]
        ),
        encoding="utf-8",
    )

    assert mark_allure_target_context.main([str(allure_dir), "192.168.22.134"]) == 0

    pending = json.loads((allure_dir / "physical_192_168_22_134_case_attachments.json").read_text(encoding="utf-8"))
    assert pending[0]["item"] == "basic_io"
    assert pending[0]["host"] == "192.168.22.134"
    assert pending[0]["target"] == "physical"
    assert pending[0]["attachment"]["source"] == "physical_192_168_22_134_case_log_env_prepare.tar.gz"
