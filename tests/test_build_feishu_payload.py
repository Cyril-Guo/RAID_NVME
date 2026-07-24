import json

from ci import build_feishu_payload


def test_failed_build_result_marks_feishu_card_failed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for key, value in {
        "TOTAL": "2",
        "FAILED": "0",
        "ERRORS": "0",
        "SKIPPED": "0",
        "BUILD_RESULT": "FAILURE",
        "START_STR": "2026-07-24 16:28:38",
        "END_STR": "2026-07-24 17:17:59",
        "IP_LIST": "192.168.22.134",
        "TRIGGER_SOURCE": "Manual MR Build (Simulate Auto MR)",
        "KERNEL_DRIVER_COMMIT": "86245fc34",
        "RAID_CLI_COMMIT": "cb0cdc7",
        "BUILD_URL": "http://jenkins/job/SMOKE/1/",
    }.items():
        monkeypatch.setenv(key, value)

    build_feishu_payload.main()

    payload = json.loads((tmp_path / "feishu_payload.json").read_text(encoding="utf-8"))
    assert payload["card"]["header"]["template"] == "red"
    fields = payload["card"]["elements"][0]["fields"]
    assert any("构建状态" in field["text"]["content"] for field in fields)
    assert any("FAILURE" in field["text"]["content"] for field in fields)
    assert "通过 **2**  失败 **0**  错误 **0**  Total: **2**" in payload["card"]["elements"][1]["text"]["content"]
