import allure

from test_items.fio_allure import (
    LARGE_CONTENT_HINT,
    attach_machinecheck_records,
    attach_named_text,
    extract_fio_job_summary,
)


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


def test_attach_named_text_uses_english_hint_for_large_content(monkeypatch):
    attached = []

    class FakeAllure:
        class attachment_type:
            TEXT = "text/plain"

        @staticmethod
        def attach(body, name=None, attachment_type=None, extension=None):
            attached.append({"name": name, "body": body})

    monkeypatch.setattr(allure, "attach", FakeAllure.attach)
    monkeypatch.setattr(allure, "attachment_type", FakeAllure.attachment_type)

    huge = "x" * (1024 * 1024 + 10)
    attach_named_text(huge, "测试结果汇总")

    names = [item["name"] for item in attached]
    assert names == ["测试结果汇总", "测试结果汇总.log"]
    assert attached[0]["body"] == LARGE_CONTENT_HINT
    assert attached[1]["body"] == huge


def test_attach_case_fio_summary_uses_this_case_output_only(monkeypatch):
    attached = []

    class FakeAllure:
        class attachment_type:
            TEXT = "text/plain"

        @staticmethod
        def attach(body, name=None, attachment_type=None, extension=None):
            attached.append({"name": name, "body": body})

    monkeypatch.setattr(allure, "attach", FakeAllure.attach)
    monkeypatch.setattr(allure, "attachment_type", FakeAllure.attachment_type)

    from test_items.fio_allure import attach_case_fio_summary

    assert attach_case_fio_summary("Job 1/4 is Running..\nJob 2/4 is Running..\n") is True
    assert attached[0]["name"] == "FIO 任务摘要"
    assert "Job 1/4 is Running.." in attached[0]["body"]
    assert "Job 2800/2800" not in attached[0]["body"]
    assert attach_case_fio_summary("no jobs here") is False


def test_attach_case_terminal_output_uses_console_attachment_name(monkeypatch):
    attached = []

    class FakeAllure:
        class attachment_type:
            TEXT = "text/plain"

        @staticmethod
        def attach(body, name=None, attachment_type=None, extension=None):
            attached.append({"name": name, "body": body})

    monkeypatch.setattr(allure, "attach", FakeAllure.attach)
    monkeypatch.setattr(allure, "attachment_type", FakeAllure.attachment_type)

    from test_items.fio_allure import CONSOLE_ATTACHMENT_NAME, attach_case_terminal_output

    assert attach_case_terminal_output("  \n") is False
    assert attached == []
    assert attach_case_terminal_output("[12:00:00] Job 1/4 is Running..\n") is True
    assert attached[0]["name"] == CONSOLE_ATTACHMENT_NAME
    assert attached[0]["body"] == "[12:00:00] Job 1/4 is Running..\n"


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
    assert [item["name"] for item in attached] == ["MachineCheck 差异记录"]
    logged = capsys.readouterr().out
    assert "IGNORE_ERROR=no, MachineCheck differences will fail the case" in logged
