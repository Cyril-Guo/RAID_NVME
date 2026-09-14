import json

from vd_io import build_feishu_payload


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


def _base_env(extra=None):
    env = {
        "TOTAL": "4",
        "FAILED": "2",
        "ERRORS": "0",
        "SKIPPED": "0",
        "REPORT_KIND": "tests",
        "BUILD_RESULT": "FAILURE",
        "JOB_NAME": "SMOKE",
        "BUILD_NUMBER": "17010",
        "BUILD_URL": "http://jenkins/job/SMOKE/17010/",
    }
    if extra:
        env.update(extra)
    return env


def test_failed_build_card_is_minimal_allure_only(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for key, value in _base_env().items():
        monkeypatch.setenv(key, value)

    build_feishu_payload.main()

    payload = json.loads((tmp_path / "feishu_payload.json").read_text(encoding="utf-8"))
    assert payload["card"]["header"]["template"] == "red"
    assert payload["card"]["header"]["title"]["content"] == "NVMe_RAID(F6501) SMOKE #17010"
    fields = payload["card"]["elements"][0]["fields"]
    field_text = "\n".join(field["text"]["content"] for field in fields)
    assert "用户名" in field_text
    assert "密码" in field_text
    assert "构建链接" not in field_text
    assert "构建状态" not in field_text
    assert "并发节点" not in field_text
    assert "触发来源" not in field_text
    assert "被测驱动" not in field_text
    body = "\n".join(str(element) for element in payload["card"]["elements"])
    assert "通过 **" not in body
    assert "执行率" not in body
    assert "通过率" not in body
    actions = payload["card"]["elements"][-1]["actions"]
    assert [action["text"]["content"] for action in actions] == ["查看报告"]
    assert actions[0]["url"] == "http://jenkins/job/SMOKE/17010/allure/"


def test_infra_failure_card_title_suffix_only(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "failure_summary.txt").write_text(
        "- environment_prepare_192.168.22.125.log: ERROR: draid kernel module load failed\n",
        encoding="utf-8",
    )
    for key, value in _base_env(
        {
            "TOTAL": "2",
            "FAILED": "0",
            "ERRORS": "2",
            "REPORT_KIND": "infra",
        }
    ).items():
        monkeypatch.setenv(key, value)

    build_feishu_payload.main()

    payload = json.loads((tmp_path / "feishu_payload.json").read_text(encoding="utf-8"))
    assert payload["card"]["header"]["title"]["content"] == (
        "NVMe_RAID(F6501) SMOKE #17010 [环境/执行失败]"
    )
    assert payload["card"]["header"]["template"] == "red"
    body = "\n".join(str(element) for element in payload["card"]["elements"])
    assert "通过 **" not in body
    assert "draid kernel module load failed" not in body
    actions = payload["card"]["elements"][-1]["actions"]
    assert [action["text"]["content"] for action in actions] == ["查看报告"]


def test_hard_fio_summary_overrides_green_junit_to_failure(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "failure_summary.txt").write_text(
        "- test_execution_192.168.22.134.log: FIO stage failed in LAWDISKSTRESS mode, "
        "model=randread bs=4m qd=32 runtime=30s (#22), elapsed=46s, planned_runtime=30s, rc=1\n",
        encoding="utf-8",
    )
    for key, value in _base_env(
        {
            "TOTAL": "1",
            "FAILED": "0",
            "ERRORS": "0",
            "BUILD_RESULT": "SUCCESS",
            "JOB_NAME": "CI",
            "BUILD_NUMBER": "35",
            "BUILD_URL": "http://192.168.23.124:8080/job/CI/35/",
        }
    ).items():
        monkeypatch.setenv(key, value)

    build_feishu_payload.main()

    payload = json.loads((tmp_path / "feishu_payload.json").read_text(encoding="utf-8"))
    assert payload["card"]["header"]["template"] == "red"
    body = "\n".join(str(element) for element in payload["card"]["elements"])
    assert "FIO stage failed" not in body
    assert payload["card"]["elements"][-1]["actions"][0]["url"].endswith("/allure/")


def test_mix_fail_on_any_no_continue_does_not_force_failure(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "failure_summary.txt").write_text(
        "- test_execution_192.168.22.134.log: FIO command failed, model=randread bs=4m qd=32 "
        "runtime=30s (#22), config=22-randread-4m-32-30.log, elapsed=46s(46s), "
        "planned_runtime=30s, rc=96\n"
        "- test_execution_192.168.22.134.log: MIX job 22 recorded FIO/disk errors "
        "rc=96/96/96/96 disks=dp0-vd1; MIX_FAIL_ON_ANY=no, continue\n",
        encoding="utf-8",
    )
    for key, value in _base_env(
        {
            "TOTAL": "1",
            "FAILED": "0",
            "ERRORS": "0",
            "BUILD_RESULT": "SUCCESS",
            "JOB_NAME": "CI",
            "BUILD_NUMBER": "35",
            "BUILD_URL": "http://192.168.23.124:8080/job/CI/35/",
        }
    ).items():
        monkeypatch.setenv(key, value)

    build_feishu_payload.main()

    payload = json.loads((tmp_path / "feishu_payload.json").read_text(encoding="utf-8"))
    assert payload["card"]["header"]["template"] == "blue"


def test_aer_only_summary_does_not_force_failure(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "failure_summary.txt").write_text(
        "- test_execution_192.168.22.134.log: aer: 0000:18:00.0 UESta=DLP- Timeout- AdvNonFatalErr-\n",
        encoding="utf-8",
    )
    for key, value in _base_env(
        {
            "TOTAL": "1",
            "FAILED": "0",
            "ERRORS": "0",
            "BUILD_RESULT": "SUCCESS",
            "JOB_NAME": "CI",
            "BUILD_NUMBER": "35",
            "BUILD_URL": "http://192.168.23.124:8080/job/CI/35/",
        }
    ).items():
        monkeypatch.setenv(key, value)

    build_feishu_payload.main()

    payload = json.loads((tmp_path / "feishu_payload.json").read_text(encoding="utf-8"))
    assert payload["card"]["header"]["template"] == "blue"
    body = "\n".join(str(element) for element in payload["card"]["elements"])
    assert "失败摘要" not in body
