from pathlib import Path

from test_items import powercycle_launch


class DummyProcess:
    pid = 12345

    def poll(self):
        return None


def test_trigger_background_fio_uses_popen_and_writes_pid(tmp_path, monkeypatch):
    calls = []

    def fake_popen(command, **kwargs):
        calls.append((command, kwargs))
        Path(kwargs["stdout"].name).write_text("launch ok\n", encoding="utf-8")
        result_log_dir = Path(kwargs["cwd"]) / "log" / "ResultLog"
        (result_log_dir / "reboot_command.log").write_text("[REBOOT] request start\n", encoding="utf-8")
        return DummyProcess()

    monkeypatch.setattr(powercycle_launch.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(powercycle_launch.time, "sleep", lambda _: None)
    monkeypatch.setattr(powercycle_launch.allure, "attach", lambda *args, **kwargs: None)

    io_stress_dir = tmp_path / "IO_Stress"
    io_stress_dir.mkdir()

    powercycle_launch.trigger_background_fio(
        str(io_stress_dir),
        "reboot",
        ["-i", "reboot", "-l", "10", "-f", "STOP"],
    )

    assert calls[0][0] == ["bash", "./powercycle_direct.sh", "-i", "reboot", "-l", "10", "-f", "STOP"]
    assert calls[0][1]["start_new_session"] is True
    assert (io_stress_dir / "log" / "ResultLog" / "reboot_launch.pid").read_text(encoding="utf-8") == "12345\n"
