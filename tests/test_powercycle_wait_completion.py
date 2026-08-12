from pathlib import Path


def test_wait_powercycle_completion_script_exists_and_checks_markers():
    source = Path("ci/wait_powercycle_completion.sh").read_text(encoding="utf-8")
    assert "BEGIN SELECTION" in source
    assert "all power-cycle loops completed" in source
    assert "Power-cycle test completed all" in source
    assert "request start" in source
    assert "POWER_CYCLE_COMPLETION_TIMEOUT_MINUTES" in source


def test_powercycle_direct_extends_reboot_grace_for_clean_ssh_exit():
    source = Path("IO_Stress/powercycle_direct.sh").read_text(encoding="utf-8")
    assert 'POWER_CYCLE_COMMAND_GRACE="${POWER_CYCLE_COMMAND_GRACE:-90}"' in source


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
