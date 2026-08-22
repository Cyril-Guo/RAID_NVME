from pathlib import Path

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


def test_smoke_cases_use_own_csv_and_do_not_import_siblings():
    sources = {
        "test_smoke_00_env_prepare.py": "run_env_prepare(log)",
        "test_smoke_01_reboot.py": 'build_fio_args("reboot", "reboot"',
        "test_smoke_02_dc.py": 'build_fio_args("dc", "dc"',
        "test_smoke_03_lawdisk.py": 'build_fio_args("lawdiskstress", "lawdisk"',
        "test_smoke_04_filesystem.py": 'build_fio_args("filesystemstress", "filesystem"',
        "test_smoke_05_mix.py": 'build_fio_args("lawdiskstress", "mix", extra=["--mix_io", "yes"]',
        "test_smoke_06_basic_io.py": 'build_fio_args("lawdiskstress", "basic_io"',
        "test_smoke_07_basic_rebuild_io.py": 'build_fio_args("lawdiskstress", "basic_rebuild_io"',
        "test_smoke_08_random_io.py": 'write_fio_job(plan, disk_sizes, fill_job, "FILL")',
    }
    for name, needle in sources.items():
        source = Path("test_items", name).read_text(encoding="utf-8")
        assert needle in source
        assert "test_smoke_03_lawdisk" not in source or name == "test_smoke_03_lawdisk.py"
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
