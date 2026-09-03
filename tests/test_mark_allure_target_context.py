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
                "labels": [{"name": "suite", "value": "test_smoke_06_basic_io"}],
                "attachments": [
                    {
                        "name": "monitor_log_basic_io",
                        "source": attachment_source,
                        "type": "application/gzip",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_mark_allure_target_context_keeps_qemu_and_physical_history_separate(tmp_path):
    qemu_dir = tmp_path / "qemu"
    physical_dir = tmp_path / "physical"
    qemu_dir.mkdir()
    physical_dir.mkdir()
    write_result(qemu_dir / "qemu-result.json", "FIO test: lawdiskstress", "same-history", "monitor_log_basic_io.tar.gz")
    write_result(physical_dir / "physical-result.json", "FIO test: lawdiskstress", "same-history", "monitor_log_basic_io.tar.gz")
    (qemu_dir / "monitor_log_basic_io.tar.gz").write_bytes(b"qemu")
    (physical_dir / "monitor_log_basic_io.tar.gz").write_bytes(b"physical")

    assert mark_allure_target_context.main([str(qemu_dir), "192.168.22.134", "", "1"]) == 0
    assert mark_allure_target_context.main([str(physical_dir), "192.168.22.134", "_physical", "0"]) == 0

    qemu = json.loads((qemu_dir / "qemu-result.json").read_text(encoding="utf-8"))
    physical = json.loads((physical_dir / "physical-result.json").read_text(encoding="utf-8"))

    assert qemu["name"] == "[QEMU 192.168.22.134] FIO test: lawdiskstress"
    assert physical["name"] == "[Physical 192.168.22.134] FIO test: lawdiskstress"
    assert qemu["historyId"] != physical["historyId"]
    assert {label["value"] for label in qemu["labels"] if label["name"] == "target"} == {"qemu"}
    assert {label["value"] for label in physical["labels"] if label["name"] == "target"} == {"physical"}
    assert qemu["attachments"][0]["source"] == "qemu_192_168_22_134_monitor_log_basic_io.tar.gz"
    assert physical["attachments"][0]["source"] == "physical_192_168_22_134_monitor_log_basic_io.tar.gz"
    assert (qemu_dir / qemu["attachments"][0]["source"]).read_bytes() == b"qemu"
    assert (physical_dir / physical["attachments"][0]["source"]).read_bytes() == b"physical"


def test_mark_allure_target_context_marks_pending_monitor_sidecar(tmp_path):
    allure_dir = tmp_path / "allure"
    allure_dir.mkdir()
    (allure_dir / "monitor_log_basic_io.tar.gz").write_bytes(b"log")
    (allure_dir / "monitor_attachments.json").write_text(
        json.dumps(
            [
                {
                    "item": "basic_io",
                    "attachment": {
                        "name": "monitor_log_basic_io",
                        "source": "monitor_log_basic_io.tar.gz",
                        "type": "application/gzip",
                    },
                }
            ]
        ),
        encoding="utf-8",
    )

    assert mark_allure_target_context.main([str(allure_dir), "192.168.22.134", "_physical", "0"]) == 0

    pending = json.loads((allure_dir / "physical_192_168_22_134_monitor_attachments.json").read_text(encoding="utf-8"))
    assert pending[0]["item"] == "basic_io"
    assert pending[0]["host"] == "192.168.22.134"
    assert pending[0]["target"] == "physical"
    assert pending[0]["attachment"]["source"] == "physical_192_168_22_134_monitor_log_basic_io.tar.gz"
