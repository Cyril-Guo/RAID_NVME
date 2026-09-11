from pathlib import Path


def test_wait_powercycle_completion_script_exists_and_checks_markers():
    source = Path("powercycle/wait_powercycle_completion.sh").read_text(encoding="utf-8")
    assert "BEGIN SELECTION" in source
    assert "all power-cycle loops completed" in source
    assert "Power-cycle test completed all" in source
    assert "request start" in source
    assert "POWER_CYCLE_COMPLETION_TIMEOUT_MINUTES" in source
    assert "item_failed" in source
    assert "cycles * 30" in source
    assert "FIO stage failed" in source
    assert "FIO command failed" in source
    assert "ERROR: MachineCheck inconsistencies found" in source
    assert "Whitelist field differences" in source
    assert "stop_flag is STOP,so exit" in source
    assert "fio_result/result.log" in source
    assert "is_powercycle_item" in source
    assert "item_short_name" in source
    assert "powercycle_log_name" in source
    assert "test_powercycle_" in source
    assert "selected_run_keys+=" in source
    assert '"${REMOTE_DIR}/cases/${run_key}/${RESULT_REL}"' in source


def test_item_failed_patterns_match_real_log_lines():
    """Guard against substring mistakes like 'FIO failed' vs 'FIO command failed'."""
    source = Path("powercycle/wait_powercycle_completion.sh").read_text(encoding="utf-8")
    start = source.index("local -a patterns=(")
    end = source.index(")", start)
    block = source[start:end]
    required = [
        "FIO command failed",
        "FIO stage failed",
        "ERROR: MachineCheck inconsistencies found",
        "Whitelist field differences",
        "stop_flag is STOP,so exit",
        "verify failed",
    ]
    for marker in required:
        assert f'"{marker}"' in block, marker


def test_powercycle_direct_extends_reboot_grace_for_clean_ssh_exit():
    source = Path("IO_Stress/powercycle_direct.sh").read_text(encoding="utf-8")
    assert 'POWER_CYCLE_COMMAND_GRACE="${POWER_CYCLE_COMMAND_GRACE:-90}"' in source


def test_powercycle_failure_paths_pass_rc_to_test_end_and_teardown_resume():
    direct = Path("IO_Stress/powercycle_direct.sh").read_text(encoding="utf-8")
    resume = Path("IO_Stress/run_fio.sh").read_text(encoding="utf-8")
    common = Path("IO_Stress/lib/common.sh").read_text(encoding="utf-8")

    assert "teardown_powercycle_resume" in common
    assert 'test_end "$fio_rc"' in direct
    assert 'test_end "$fio_rc"' in resume
    assert "teardown_powercycle_resume" in direct
    assert "teardown_powercycle_resume" in resume
    assert "test_end\n        exit $fio_rc" not in direct
    assert "test_end\n        exit $fio_rc" not in resume
    assert "info_rc" in direct
    assert 'flag" == "STOP"' in direct


def test_powercycle_force_once_is_one_shot():
    source = Path("IO_Stress/lib/fio_powercycle.sh").read_text(encoding="utf-8")
    assert "export POWER_CYCLE_FORCE_ONCE=0" in source
    assert "stale loop>=LOOP on initial trigger" in source


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
            "[REBOOT] request start\n", encoding="utf-8"
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
