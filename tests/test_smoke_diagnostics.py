import json
import tarfile
from pathlib import Path

from test_items.basic_io_common import CommandLog


def test_command_log_survives_broken_console(tmp_path, monkeypatch):
    monkeypatch.setenv("RAID_NVME_CASE_ROOT", str(tmp_path))
    def broken(*args, **kwargs):
        raise BrokenPipeError("closed")
    monkeypatch.setattr("builtins.print", broken)
    log = CommandLog()
    log.write("[CMD_START] dpraid /c0 show vd")
    assert "dpraid /c0 show vd" in log.lines[-1]
    assert "dpraid /c0 show vd" in (tmp_path / "case_command.log").read_text()


def test_salvage_recovers_interrupted_case_artifacts(tmp_path):
    from ci.salvage_case_artifacts import recover_case_artifacts
    case = tmp_path / "cases" / "multi_raid_io"
    logs = case / "IO_Stress" / "log"
    logs.mkdir(parents=True)
    (logs / "fio.log").write_text("fio: Input/output error\n")
    (case / "case_command.log").write_text("[CMD_START] dpraid\n")
    (case / "report_multi_raid_io.xml").write_text('<testsuite><testcase name="test_multi_raid_io" /></testsuite>')
    recover_case_artifacts(tmp_path, ["multi_raid_io"])
    root = tmp_path / "allure-results"
    pending = json.loads((root / "recovered_monitor_attachments.json").read_text())
    assert pending[0]["item"] == "multi_raid_io"
    with tarfile.open(root / pending[0]["attachment"]["source"]) as archive:
        assert "IO_Stress/log/fio.log" in archive.getnames()
        assert "case_command.log" in archive.getnames()
    assert (tmp_path / "report_multi_raid_io.xml").exists()
    recover_case_artifacts(tmp_path, ["multi_raid_io"])
    assert len(json.loads((root / "recovered_monitor_attachments.json").read_text())) == 1
    monitor = tmp_path / "Stress_Monitor" / "log"
    monitor.mkdir(parents=True)
    (monitor / "iostat.log").write_text("monitor snapshot\n")
    recover_case_artifacts(tmp_path, ["multi_raid_io"])
    pending = json.loads((root / "recovered_monitor_attachments.json").read_text())
    shared = next(entry for entry in pending if entry.get("scope") == "node")
    with tarfile.open(root / shared["attachment"]["source"]) as archive:
        assert "Stress_Monitor/log/iostat.log" in archive.getnames()


def test_nested_attachment_is_renamed_and_sidecars_are_host_specific(tmp_path):
    from ci.mark_allure_target_context import main
    (tmp_path / "commands.txt").write_text("dpraid\n")
    (tmp_path / "partial-result.json").write_text('{"name":')
    result = tmp_path / "one-result.json"
    result.write_text(json.dumps({"name": "multi", "steps": [{"name": "FIO", "attachments": [
        {"name": "cmd", "source": "commands.txt"}]}]}))
    (tmp_path / "recovered_monitor_attachments.json").write_text("[]")
    fixture = tmp_path / "one-container.json"
    fixture.write_text(json.dumps({"befores": [{"attachments": [{"source": "commands.txt"}]}]}))
    main([str(tmp_path), "192.168.22.134", "", "0"])
    data = json.loads(result.read_text())
    assert (tmp_path / data["steps"][0]["attachments"][0]["source"]).exists()
    assert list(tmp_path.glob("physical_192_168_22_134_*monitor_attachments.json"))
    assert (tmp_path / json.loads(fixture.read_text())["befores"][0]["attachments"][0]["source"]).exists()


def test_watchdog_diagnoses_before_kill_and_bounds_collection():
    text = Path("ci/run_remote_test_and_collect.sh").read_text()
    watchdog = text[text.index('idle_timed_out=1'):]
    assert watchdog.index("collect_failure_diagnostics\n") < watchdog.index('kill -TERM "-${test_pid}"')
    assert "python3 -u nvme_raid_test.py" in text
    assert text.index('record_failure "${test_rc}"') < text.index("ci/salvage_junit_reports.py")
    assert "timeout --kill-after=5s" in text
    assert "eval " not in text
