from pathlib import Path

from test_items.fio_run import build_fio_args


def test_build_fio_args_for_powercycle(monkeypatch):
    monkeypatch.setenv("IGNORE_ERROR", "yes")
    monkeypatch.delenv("FIO_DISKS", raising=False)

    assert build_fio_args("reboot", "reboot", extra=["-l", "100"]) == [
        "-i",
        "reboot",
        "-f",
        "NON-STOP",
        "-l",
        "100",
    ]

    monkeypatch.setenv("IGNORE_ERROR", "no")
    monkeypatch.setenv("FIO_DISKS", "nvme2n1,nvme3n1")
    assert build_fio_args("dc", "dc", extra=["-l", "5"]) == [
        "-i",
        "dc",
        "-f",
        "STOP",
        "-l",
        "5",
        "-u",
        "nvme2n1,nvme3n1",
    ]


def test_powercycle_cases_use_build_fio_args_without_static_csv():
    root = Path(__file__).resolve().parents[1] / "test_items"
    for name in ("test_powercycle_01_reboot.py", "test_powercycle_02_dc.py"):
        source = (root / name).read_text(encoding="utf-8")
        assert "build_fio_args(" in source
        assert "Input_Config_" not in source
        assert "run_and_check" not in source
