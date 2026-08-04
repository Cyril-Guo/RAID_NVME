import json

from ci import build_feishu_payload


def test_zero_total_does_not_generate_feishu_payload(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    stale_payload = tmp_path / "feishu_payload.json"
    stale_payload.write_text('{"stale": true}', encoding="utf-8")
    monkeypatch.setenv("TOTAL", "0")
    monkeypatch.setenv("FAILED", "0")
    monkeypatch.setenv("ERRORS", "0")
    monkeypatch.setenv("SKIPPED", "0")

    build_feishu_payload.main()

    assert not stale_payload.exists()
    assert "NO_FEISHU_PAYLOAD=empty_metrics" in capsys.readouterr().out


def test_failed_build_result_marks_feishu_card_failed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for key, value in {
        "TOTAL": "4",
        "FAILED": "2",
        "ERRORS": "0",
        "SKIPPED": "0",
        "REPORT_KIND": "tests",
        "BUILD_RESULT": "FAILURE",
        "START_STR": "2026-07-24 16:28:38",
        "END_STR": "2026-07-24 17:17:59",
        "IP_LIST": "192.168.22.134",
        "TRIGGER_SOURCE": "Manual MR Build (Simulate Auto MR)",
        "KERNEL_DRIVER_REF": "led_develop",
        "KERNEL_DRIVER_COMMIT": "86245fc34",
        "RAID_CLI_COMMIT": "cb0cdc7",
        "JOB_NAME": "SMOKE",
        "BUILD_NUMBER": "17010",
        "BUILD_URL": "http://jenkins/job/SMOKE/17010/",
    }.items():
        monkeypatch.setenv(key, value)

    build_feishu_payload.main()

    payload = json.loads((tmp_path / "feishu_payload.json").read_text(encoding="utf-8"))
    assert payload["card"]["header"]["template"] == "red"
    assert payload["card"]["header"]["title"]["content"] == "NVMe_RAID(F6501) SMOKE #17010"
    fields = payload["card"]["elements"][0]["fields"]
    field_text = "\n".join(field["text"]["content"] for field in fields)
    assert "Jenkins构建" in field_text
    assert "SMOKE #17010" in field_text
    assert "构建链接" in field_text
    assert "http://jenkins/job/SMOKE/17010/" in field_text
    assert "并发节点" in field_text
    assert any("构建状态" in field["text"]["content"] for field in fields)
    assert any("FAILURE" in field["text"]["content"] for field in fields)
    stats = payload["card"]["elements"][1]["text"]["content"]
    assert "通过 **2**  失败 **2**  错误 **0**  Total: **4**" in stats
    assert "执行率: 100.00%" in stats
    assert "通过率:" in stats
    assert "50.0%" in stats
    body = "\n".join(str(element) for element in payload["card"]["elements"])
    assert "报告类型" not in body
    assert "失败摘要" not in body
    actions = payload["card"]["elements"][-1]["actions"]
    assert [action["text"]["content"] for action in actions] == ["查看报告", "查看MR"]
    assert actions[0]["url"] == "http://jenkins/job/SMOKE/17010/allure/"
    assert actions[1]["url"] == "http://192.168.21.185:8081/raid_max/kernel_driver/-/commit/86245fc34"


def test_infra_failure_card_shows_stats_without_summary(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "failure_summary.txt").write_text(
        "- environment_prepare_192.168.22.125.log: ERROR: QEMU VM startup failed\n",
        encoding="utf-8",
    )
    for key, value in {
        "TOTAL": "2",
        "FAILED": "0",
        "ERRORS": "2",
        "SKIPPED": "0",
        "REPORT_KIND": "infra",
        "BUILD_RESULT": "FAILURE",
        "START_STR": "2026-08-04 14:30:01",
        "END_STR": "2026-08-04 14:37:42",
        "IP_LIST": "192.168.22.125, 192.168.22.134",
        "TRIGGER_SOURCE": "kernel_driver Merge Request",
        "KERNEL_DRIVER_COMMIT": "daed195f3",
        "KERNEL_DRIVER_MR_URL": "http://192.168.21.185:8081/raid_max/kernel_driver/-/merge_requests/141",
        "JOB_NAME": "SMOKE",
        "BUILD_NUMBER": "17010",
        "BUILD_URL": "http://jenkins/job/SMOKE/17010/",
    }.items():
        monkeypatch.setenv(key, value)

    build_feishu_payload.main()

    payload = json.loads((tmp_path / "feishu_payload.json").read_text(encoding="utf-8"))
    assert payload["card"]["header"]["title"]["content"] == "NVMe_RAID(F6501) SMOKE #17010 [环境/执行失败]"
    assert payload["card"]["header"]["template"] == "red"
    stats = payload["card"]["elements"][1]["text"]["content"]
    assert "通过 **0**  失败 **0**  错误 **2**  Total: **2**" in stats
    assert "通过率:" in stats
    assert "0.0%" in stats
    body = "\n".join(str(element) for element in payload["card"]["elements"])
    assert "环境准备/远端执行失败" not in body
    assert "失败摘要" not in body
    assert "QEMU VM startup failed" not in body
    actions = payload["card"]["elements"][-1]["actions"]
    assert [action["text"]["content"] for action in actions] == ["查看报告", "查看MR"]
    assert actions[1]["url"] == "http://192.168.21.185:8081/raid_max/kernel_driver/-/merge_requests/141"
