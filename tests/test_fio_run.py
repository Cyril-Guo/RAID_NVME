from pathlib import Path

import pytest

from test_items import fio_run
from test_items.fio_run import build_fio_args, resolve_fio_csv


def test_resolve_fio_csv_uses_case_file(tmp_path, monkeypatch):
    io_stress = tmp_path / "IO_Stress"
    io_stress.mkdir()
    (io_stress / "Input_Config_lawdisk.csv").write_text("header\n4k,100,100,64,30,24,0\n", encoding="utf-8")
    monkeypatch.setenv("RAID_NVME_CASE_ROOT", str(tmp_path))
    monkeypatch.delenv("FIO_CONFIG", raising=False)

    assert resolve_fio_csv("lawdisk") == "Input_Config_lawdisk.csv"


def test_resolve_fio_csv_honors_fio_config_override(tmp_path, monkeypatch):
    io_stress = tmp_path / "IO_Stress"
    io_stress.mkdir()
    (io_stress / "custom_mix.csv").write_text("header\n", encoding="utf-8")
    monkeypatch.setenv("RAID_NVME_CASE_ROOT", str(tmp_path))
    monkeypatch.setenv("FIO_CONFIG", "custom_mix.csv")

    assert resolve_fio_csv("mix") == "custom_mix.csv"


def test_build_fio_args_passes_case_csv(tmp_path, monkeypatch):
    io_stress = tmp_path / "IO_Stress"
    io_stress.mkdir()
    (io_stress / "Input_Config_mix.csv").write_text("header\n", encoding="utf-8")
    monkeypatch.setenv("RAID_NVME_CASE_ROOT", str(tmp_path))
    monkeypatch.delenv("FIO_CONFIG", raising=False)
    monkeypatch.setenv("IGNORE_ERROR", "yes")
    monkeypatch.delenv("FIO_DISKS", raising=False)

    args = build_fio_args("lawdiskstress", "mix", extra=["--mix_io", "yes"])
    assert args == [
        "-i",
        "lawdiskstress",
        "-f",
        "NON-STOP",
        "-n",
        "Input_Config_mix.csv",
        "--mix_io",
        "yes",
    ]


def test_ci_cases_use_own_csv_and_do_not_import_siblings():
    sources = {
        "test_ci_00_env_prepare.py": "run_env_prepare(log)",
        "test_ci_01_reboot.py": 'build_fio_args("reboot", "reboot"',
        "test_ci_02_dc.py": 'build_fio_args("dc", "dc"',
        "test_ci_03_lawdisk.py": 'build_fio_args("lawdiskstress", "lawdisk"',
        "test_ci_04_filesystem.py": 'build_fio_args("filesystemstress", "filesystem"',
        "test_ci_05_mix.py": 'build_fio_args("lawdiskstress", "mix", extra=["--mix_io", "yes"]',
        "test_ci_06_basic_io.py": 'build_fio_args("lawdiskstress", "basic_io"',
        "test_ci_07_basic_rebuild_io.py": 'build_fio_args("lawdiskstress", "basic_rebuild_io"',
        "test_ci_08_random_io.py": 'write_fio_job(plan, disk_sizes, jobs["FILL"], "FILL")',
    }
    for name, needle in sources.items():
        source = Path("test_items", name).read_text(encoding="utf-8")
        assert needle in source
        assert "test_ci_03_lawdisk" not in source or name == "test_ci_03_lawdisk.py"
        assert "as lawdisk_case" not in source
        assert "prepare_physical_io_case" not in source
    for item in (
        "reboot",
        "dc",
        "lawdisk",
        "filesystem",
        "mix",
        "basic_io",
        "basic_rebuild_io",
        "random_io",
    ):
        assert Path("IO_Stress", f"Input_Config_{item}.csv").is_file()


class _FakeProcess:
    def __init__(self, lines, returncode):
        self.stdout = iter(lines)
        self.returncode = returncode

    def wait(self):
        return self.returncode


def _configure_fio_runner(monkeypatch, tmp_path, lines, returncode, attachments):
    monkeypatch.setenv("RAID_NVME_CASE_ROOT", str(tmp_path))
    monkeypatch.setenv("RAID_NVME_RUN_KEY", "mix__2")
    monkeypatch.delenv("IGNORE_ERROR", raising=False)
    monkeypatch.setattr(
        fio_run.subprocess,
        "Popen",
        lambda *args, **kwargs: _FakeProcess(lines, returncode),
    )
    monkeypatch.setattr(
        fio_run,
        "attach_case_terminal_output",
        lambda text, output_path=None: attachments.append(("terminal", text, output_path)),
    )
    monkeypatch.setattr(fio_run, "attach_case_fio_summary", lambda text: False)
    monkeypatch.setattr(fio_run, "attach_machinecheck_records", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        fio_run,
        "attach_named_text",
        lambda text, name: attachments.append((name, text, None)),
    )


def test_run_and_check_argv_keeps_running_when_console_pipe_closes(monkeypatch, tmp_path):
    attachments = []
    _configure_fio_runner(
        monkeypatch,
        tmp_path,
        ["Job 1/4 is Running..\n", "PASSED\n"],
        0,
        attachments,
    )
    monkeypatch.setattr("test_items.command_output.safe_console_write", lambda *_args, **_kwargs: False)

    output = fio_run.run_and_check_argv(["fio", "mix.fio"], cwd=str(tmp_path))

    assert "PASSED" in output
    assert "stdout pipe closed" in output
    terminal = next(item for item in attachments if item[0] == "terminal")
    persisted = Path(terminal[2])
    assert persisted.is_file()
    assert "Job 1/4 is Running.." in persisted.read_text(encoding="utf-8")
    assert "console_mirror=closed" in persisted.read_text(encoding="utf-8")


def test_run_and_check_argv_reports_fio_root_cause_not_broken_pipe(monkeypatch, tmp_path):
    attachments = []
    _configure_fio_runner(
        monkeypatch,
        tmp_path,
        [
            "fio: io_u error on file /dev/dp0-vd1: Input/output error\n",
            "FIO stage failed in LAWDISKSTRESS mode, model=randrw rc=1\n",
        ],
        1,
        attachments,
    )
    monkeypatch.setattr("test_items.command_output.safe_console_write", lambda *_args, **_kwargs: False)

    with pytest.raises(pytest.fail.Exception) as exc_info:
        fio_run.run_and_check_argv(["bash", "./Fio_All.sh"], cwd=str(tmp_path))

    message = str(exc_info.value)
    assert message.startswith("FIO 脚本执行失败")
    assert "exit_code=1" in message
    assert "primary_error=fio: io_u error" in message
    assert "BrokenPipeError" not in message
    summary = next(item for item in attachments if item[0] == "FIO 故障摘要")
    assert "FIO stage failed" in summary[1]
