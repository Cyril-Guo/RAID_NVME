from pathlib import Path

from test_items.fio_run import build_fio_args, resolve_fio_csv


def test_resolve_fio_csv_uses_env_or_default(tmp_path, monkeypatch):
    io_stress = tmp_path / "IO_Stress"
    io_stress.mkdir()
    (io_stress / "Input_Config_reboot.csv").write_text("header\n", encoding="utf-8")
    (io_stress / "Input_Config_reboot_4k.csv").write_text("header\n", encoding="utf-8")
    monkeypatch.setenv("RAID_NVME_CASE_ROOT", str(tmp_path))
    monkeypatch.delenv("FIO_CONFIG", raising=False)

    assert resolve_fio_csv("reboot") == "Input_Config_reboot.csv"

    monkeypatch.setenv("FIO_CONFIG", "Input_Config_reboot_4k.csv")
    assert resolve_fio_csv("reboot") == "Input_Config_reboot_4k.csv"


def test_build_fio_args_for_powercycle(tmp_path, monkeypatch):
    io_stress = tmp_path / "IO_Stress"
    io_stress.mkdir()
    (io_stress / "Input_Config_reboot_4k.csv").write_text("header\n", encoding="utf-8")
    (io_stress / "Input_Config_dc_4k.csv").write_text("header\n", encoding="utf-8")
    monkeypatch.setenv("RAID_NVME_CASE_ROOT", str(tmp_path))
    monkeypatch.setenv("FIO_CONFIG", "Input_Config_reboot_4k.csv")
    monkeypatch.setenv("IGNORE_ERROR", "yes")
    monkeypatch.delenv("FIO_DISKS", raising=False)

    assert build_fio_args("reboot", "reboot", extra=["-l", "100"]) == [
        "-i",
        "reboot",
        "-f",
        "NON-STOP",
        "-n",
        "Input_Config_reboot_4k.csv",
        "-l",
        "100",
    ]

    monkeypatch.setenv("FIO_CONFIG", "Input_Config_dc_4k.csv")
    monkeypatch.setenv("IGNORE_ERROR", "no")
    monkeypatch.setenv("FIO_DISKS", "nvme2n1,nvme3n1")
    assert build_fio_args("dc", "dc", extra=["-l", "5"]) == [
        "-i",
        "dc",
        "-f",
        "STOP",
        "-n",
        "Input_Config_dc_4k.csv",
        "-l",
        "5",
        "-u",
        "nvme2n1,nvme3n1",
    ]


def test_powercycle_cases_use_build_fio_args():
    root = Path(__file__).resolve().parents[1] / "test_items"
    mapping = {
        "test_powercycle_01_reboot.py": 'build_fio_args("reboot", "reboot"',
        "test_powercycle_02_dc.py": 'build_fio_args("dc", "dc"',
    }
    for name, needle in mapping.items():
        source = (root / name).read_text(encoding="utf-8")
        assert needle in source
        assert "run_and_check" not in source
