import gzip
import allure

from test_items.fio_allure import attach_terminal_output, extract_fio_job_summary


def test_extract_fio_job_summary_lists_all_running_jobs_first():
    sample = "\n".join(
        [
            "[FIO] start model=randrw (#1)",
            "Job 1/2800 is Running..",
            "[FIO] finish model=randrw (#1) rc=0 elapsed=36s",
            "Job 2/2800 is Running..",
            "[FIO] finish model=randrw (#2) rc=4 elapsed=30s",
            "[FIO] partial disk failure recorded; at least one disk had IO, continue",
            "Job 2800/2800 is Running..",
            "[FIO] finish model=randrw (#2800) rc=0 elapsed=31s",
        ]
    )

    summary = extract_fio_job_summary(sample)
    assert "job_running_lines=3" in summary
    jobs_section = summary.split("===== errors =====")[0]
    assert "Job 1/2800 is Running.." in jobs_section
    assert "Job 2/2800 is Running.." in jobs_section
    assert "Job 2800/2800 is Running.." in jobs_section
    assert "partial disk failure recorded" in summary
    assert jobs_section.find("Job 1/2800") < jobs_section.find("Job 2800/2800")


def test_attach_terminal_output_gzips_large_logs(monkeypatch):
    attached = []

    class FakeAllure:
        class attachment_type:
            TEXT = "text/plain"

        @staticmethod
        def attach(body, name=None, attachment_type=None, extension=None):
            attached.append(
                {
                    "name": name,
                    "attachment_type": attachment_type,
                    "extension": extension,
                    "body": body,
                }
            )

    monkeypatch.setattr(allure, "attach", FakeAllure.attach)
    monkeypatch.setattr(allure, "attachment_type", FakeAllure.attachment_type)

    huge = ("Job 1/2800 is Running..\n" + ("x" * 2000 + "\n") * 600)
    attach_terminal_output(huge)

    names = [item["name"] for item in attached]
    assert "FIO 任务摘要" in names
    assert "终端完整输出.log.gz" in names
    gz_item = next(item for item in attached if item["name"] == "终端完整输出.log.gz")
    assert gzip.decompress(gz_item["body"]).decode("utf-8").startswith("Job 1/2800")


def test_attach_machinecheck_records_always_attaches_detail_log(tmp_path, monkeypatch, capsys):
    attached = []

    class FakeAllure:
        class attachment_type:
            TEXT = "text/plain"

        @staticmethod
        def attach(body, name=None, attachment_type=None, extension=None):
            attached.append({"name": name, "body": body})

    monkeypatch.setattr(allure, "attach", FakeAllure.attach)
    monkeypatch.setattr(allure, "attachment_type", FakeAllure.attachment_type)

    from test_items.fio_allure import attach_machinecheck_records

    detail_dir = tmp_path / "log" / "TestErrorLog"
    detail_dir.mkdir(parents=True)
    (detail_dir / "machine_diff_error.log").write_text(
        "ERROR: MachineCheck Log Inconsistency Detected!\n"
        "[CHANGED] link: 0000:e1:00.0\n"
        "  LnkSta_Speed: 16GT/s -> 8GT/s\n",
        encoding="utf-8",
    )

    assert attach_machinecheck_records(str(tmp_path), ignore_error=True) is True
    record = next(item for item in attached if item["name"] == "MachineCheck 差异记录")
    assert "LnkSta_Speed: 16GT/s -> 8GT/s" in record["body"]
    logged = capsys.readouterr().out
    assert "MachineCheck differences recorded" in logged
    assert "IGNORE_ERROR=yes, record MachineCheck without failing" in logged

    attached.clear()
    assert attach_machinecheck_records(str(tmp_path), ignore_error=False) is True
    assert any(item["name"] == "MachineCheck 差异记录" for item in attached)
    logged = capsys.readouterr().out
    assert "IGNORE_ERROR=no, MachineCheck differences will fail the case" in logged
