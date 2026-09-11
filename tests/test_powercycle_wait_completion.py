from pathlib import Path


def test_wait_powercycle_completion_script_exists_and_checks_markers():
    source = Path("powercycle/wait_powercycle_completion.sh").read_text(encoding="utf-8")
    assert "BEGIN SELECTION" in source
    assert "all power-cycle loops completed" in source
    assert "Power-cycle test completed all" in source
    assert "request start" in source
    assert "POWER_CYCLE_COMPLETION_TIMEOUT_MINUTES" in source
    assert "item_failed" in source
    assert "read_item_ignore_error" in source
    assert "cycles * 30" in source
    assert "FIO stage failed" in source
    assert "FIO command failed" in source
    assert "Power-cycle reboot/dc command failed" in source
    assert "fio_result/result.log" in source
    assert "Whitelist field differences" in source
    assert "ignore_error" in source


def test_item_failed_machinecheck_markers_gated_by_ignore_error():
    source = Path("powercycle/wait_powercycle_completion.sh").read_text(encoding="utf-8")
    assert "read_item_ignore_error" in source
    assert '"FIO command failed"' in source
    assert '"Power-cycle reboot/dc command failed"' in source
    assert "Whitelist field differences" in source
    assert '[[ "${ignore_error}" != "yes" ]]' in source


def test_powercycle_direct_extends_reboot_grace_for_clean_ssh_exit():
    source = Path("IO_Stress/powercycle_direct.sh").read_text(encoding="utf-8")
    assert 'POWER_CYCLE_COMMAND_GRACE="${POWER_CYCLE_COMMAND_GRACE:-90}"' in source


def test_powercycle_failure_paths_pass_rc_to_test_end_and_teardown_resume():
    direct = Path("IO_Stress/powercycle_direct.sh").read_text(encoding="utf-8")
    resume = Path("IO_Stress/run_fio.sh").read_text(encoding="utf-8")
    common = Path("IO_Stress/lib/common.sh").read_text(encoding="utf-8")
    fio = Path("IO_Stress/lib/fio.sh").read_text(encoding="utf-8")
    diff = Path("IO_Stress/lib/diff.sh").read_text(encoding="utf-8")
    power = Path("IO_Stress/lib/fio_powercycle.sh").read_text(encoding="utf-8")
    assert "teardown_powercycle_resume" in common
    assert "teardown_powercycle_resume" in fio
    assert 'test_end "$fio_rc"' in direct
    assert 'test_end "$fio_rc"' in resume
    assert "TESTS FAILED" in fio
    assert "teardown_powercycle_resume" in diff
    assert "request_system_reboot || exit" not in power
    assert 'return "$reboot_fail_rc"' in power
    assert "unsupported DC mode" in power
    idx = fio.index("Fail to detect system disk")
    window = fio[idx : idx + 250]
    assert "return 1" in window
    assert "exit 1" not in window


def test_powercycle_force_once_is_one_shot():
    source = Path("IO_Stress/lib/fio_powercycle.sh").read_text(encoding="utf-8")
    assert "export POWER_CYCLE_FORCE_ONCE=0" in source
    assert "stale loop>=LOOP on initial trigger" in source


def test_powercycle_scripts_have_no_hardcoded_password_default():
    for rel in (
        "powercycle/deploy_workspace.sh",
        "powercycle/install_dpraid_remote.sh",
        "powercycle/prepare_draid_driver.sh",
        "powercycle/reclaim_physical_host.sh",
    ):
        text = Path(rel).read_text(encoding="utf-8")
        assert ":-123456" not in text, rel
        assert "${TARGET_PASSWORD:-123456}" not in text, rel


def test_powercycle_launch_defaults_command_grace(tmp_path, monkeypatch):
    from test_items import powercycle_launch

    class DummyProcess:
        pid = 42

        def poll(self):
            return None

    captured = {}

    def fake_popen(command, **kwargs):
        captured["env"] = kwargs["env"]
        result_log_dir = Path(kwargs["cwd"]) / "log" / "ResultLog"
        (result_log_dir / "reboot_command.log").write_text(
            "[REBOOT] request start\n",
            encoding="utf-8",
        )
        return DummyProcess()

    monkeypatch.setattr(powercycle_launch.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(powercycle_launch.time, "sleep", lambda _: None)
    monkeypatch.setattr(powercycle_launch.allure, "attach", lambda *args, **kwargs: None)
    monkeypatch.delenv("POWER_CYCLE_COMMAND_GRACE", raising=False)

    io_stress_dir = tmp_path / "IO_Stress"
    io_stress_dir.mkdir()
    powercycle_launch.trigger_background_fio(
        str(io_stress_dir), "reboot", ["-i", "reboot", "-l", "1", "-f", "STOP"]
    )
    assert captured["env"]["POWER_CYCLE_COMMAND_GRACE"] == "90"
