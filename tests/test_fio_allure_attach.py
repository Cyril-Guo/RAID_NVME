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
