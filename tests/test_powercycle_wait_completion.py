from pathlib import Path


def test_wait_powercycle_completion_script_exists_and_checks_markers():
    source = Path("powercycle/wait_powercycle_completion.sh").read_text(encoding="utf-8")
    assert "BEGIN SELECTION" in source
    assert "all power-cycle loops completed" in source
    assert "read_item_ignore_error" in source
    assert "item_short_name" in source
    assert "FIO command failed" in source
    assert "Power-cycle reboot/dc command failed" in source
    assert "Whitelist field differences" in source
    assert '[[ "${ignore_error}" != "yes" ]]' in source


def test_powercycle_done_rc_is_ten_not_two():
    power = Path("IO_Stress/lib/fio_powercycle.sh").read_text(encoding="utf-8")
    direct = Path("IO_Stress/powercycle_direct.sh").read_text(encoding="utf-8")
    resume = Path("IO_Stress/run_fio.sh").read_text(encoding="utf-8")
    assert "return 10" in power
    assert "unsupported DC mode" in power
    assert "return 22" in power
    assert "reboot_rc -eq 10" in direct or "[ $reboot_rc -eq 10 ]" in direct
    assert "[ $reboot_rc -eq 10 ]" in resume
    assert "reboot_rc -eq 2" not in direct
    assert "[ $reboot_rc -eq 2 ]" not in resume


def test_dc_poweroff_failure_does_not_exit_zero():
    power = Path("IO_Stress/lib/fio_powercycle.sh").read_text(encoding="utf-8")
    assert "poweroff" in power
    # dc helpers return poweroff status; caller checks dc_rc
    assert "return $?" in power
    assert "dc_rc=$?" in power
    assert "DC poweroff failed" in power
    assert "_rollback_powercycle_loop" in power


def test_jenkins_wires_powercycle_completion_timeout():
    jenkinsfile = Path("Jenkinsfile").read_text(encoding="utf-8")
    assert "POWER_CYCLE_COMPLETION_TIMEOUT_MINUTES = '4000'" in jenkinsfile
    assert "POWER_CYCLE_COMPLETION_TIMEOUT_MINUTES='${env.POWER_CYCLE_COMPLETION_TIMEOUT_MINUTES}'" in jenkinsfile


def test_powercycle_failure_paths_and_teardown():
    fio = Path("IO_Stress/lib/fio.sh").read_text(encoding="utf-8")
    diff = Path("IO_Stress/lib/diff.sh").read_text(encoding="utf-8")
    common = Path("IO_Stress/lib/common.sh").read_text(encoding="utf-8")
    power = Path("IO_Stress/lib/fio_powercycle.sh").read_text(encoding="utf-8")
    assert "TESTS FAILED" in fio
    assert "teardown_powercycle_resume" in fio
    assert "teardown_powercycle_resume" in diff
    assert "teardown_powercycle_resume" in common
    assert "declare -F teardown_powercycle_resume" in common  # EXIT trap
    # Intentional reboot/dc exit must keep resume unit armed.
    assert '[[ "${POWERCYCLE_KEEP_RESUME:-0}" != "1" ]]' in common
    assert power.count("POWERCYCLE_KEEP_RESUME=1") >= 2


def test_powercycle_scripts_have_no_hardcoded_password_default():
    for rel in (
        "powercycle/deploy_workspace.sh",
        "powercycle/install_dpraid_remote.sh",
        "powercycle/prepare_draid_driver.sh",
        "powercycle/reclaim_physical_host.sh",
    ):
        text = Path(rel).read_text(encoding="utf-8")
        assert ":-123456" not in text, rel


def test_powercycle_direct_extends_reboot_grace_for_clean_ssh_exit():
    source = Path("IO_Stress/powercycle_direct.sh").read_text(encoding="utf-8")
    assert 'POWER_CYCLE_COMMAND_GRACE="${POWER_CYCLE_COMMAND_GRACE:-90}"' in source
    power = Path("IO_Stress/lib/fio_powercycle.sh").read_text(encoding="utf-8")
    assert "POWER_CYCLE_COMMAND_GRACE:-90" in power


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
        (result_log_dir / "reboot_command.log").write_text("[REBOOT] request start\n", encoding="utf-8")
        return DummyProcess()

    monkeypatch.setattr(powercycle_launch.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(powercycle_launch.time, "sleep", lambda _: None)
    monkeypatch.setattr(powercycle_launch.allure, "attach", lambda *args, **kwargs: None)
    monkeypatch.delenv("POWER_CYCLE_COMMAND_GRACE", raising=False)
    io_stress_dir = tmp_path / "IO_Stress"
    io_stress_dir.mkdir()
    powercycle_launch.trigger_background_fio(str(io_stress_dir), "reboot", ["-i", "reboot", "-l", "1", "-f", "STOP"])
    assert captured["env"]["POWER_CYCLE_COMMAND_GRACE"] == "90"

def test_wait_unreachable_trigger_is_gated():
    source = Path("powercycle/wait_powercycle_completion.sh").read_text(encoding="utf-8")
    assert "POWER_CYCLE_ALLOW_UNREACHABLE_TRIGGER" in source
    assert "Invalid arguments" in source
    assert "reboot_rc=10" in source


def test_arguments_numeric_exits_are_nonzero():
    source = Path("IO_Stress/lib/arguments.sh").read_text(encoding="utf-8")
    assert "the input S0 delay time isn't a number,exit" in source
    assert "the input runtime isn't a number,exit" in source
    # Both delay/runtime paths must use exit 2 (not bare exit).
    delay_idx = source.index("the input S0 delay time isn't a number,exit")
    runtime_idx = source.index("the input runtime isn't a number,exit")
    assert "exit 2" in source[delay_idx:delay_idx + 80]
    assert "exit 2" in source[runtime_idx:runtime_idx + 80]
    assert "Invalid flag=" in source


def test_grace_propagates_into_resume_unit():
    common = Path("IO_Stress/lib/common.sh").read_text(encoding="utf-8")
    assert "Environment=POWER_CYCLE_COMMAND_GRACE=" in common
    assert 'export POWER_CYCLE_COMMAND_GRACE="${POWER_CYCLE_COMMAND_GRACE:-90}"' in common
    direct = Path("IO_Stress/powercycle_direct.sh").read_text(encoding="utf-8")
    assert "\ndotrap\n" in direct or "dotrap" in direct


def test_run_fio_rejects_reboot_rc_zero_fallthrough():
    resume = Path("IO_Stress/run_fio.sh").read_text(encoding="utf-8")
    assert "unexpected do_reboot rc=" in resume
    assert "reached unexpected fallthrough" in resume


def test_powercycle_state_commit_deferred_until_reboot():
    fio = Path("IO_Stress/lib/fio.sh").read_text(encoding="utf-8")
    power = Path("IO_Stress/lib/fio_powercycle.sh").read_text(encoding="utf-8")
    assert "staged powercycle state pending" in fio
    assert power.count("commit_powercycle_state") >= 3
    assert 'rm -f "$POWERCYCLE_STATE_NEXT_FILE"' in power


def test_jenkins_allows_unreachable_trigger_after_pytest():
    jenkinsfile = Path("Jenkinsfile").read_text(encoding="utf-8")
    assert "POWER_CYCLE_ALLOW_UNREACHABLE_TRIGGER='1'" in jenkinsfile

