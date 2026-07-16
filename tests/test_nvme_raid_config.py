from pathlib import Path

import nvme_raid_test
from nvme_raid_test import parse_items_file


def test_repository_test_items_file_is_valid():
    config = Path(__file__).resolve().parents[1] / "test_items.txt"

    selected, params = parse_items_file(config)

    assert selected
    assert "mix" in params


def test_parse_selection_block_controls_enabled_items(tmp_path):
    config = tmp_path / "test_items.txt"
    config.write_text(
        """
[selection]
reboot = no
dc = yes
mix = yes

[dc]
FIO_CYCLES = 3
IGNORE_ERROR = no

[mix]
FIO_DISKS = sdb,sdc
""",
        encoding="utf-8",
    )

    selected, params = parse_items_file(config)

    assert selected == ["dc", "mix"]
    assert params["dc"]["FIO_CYCLES"] == "3"
    assert params["mix"]["FIO_DISKS"] == "sdb,sdc"


def test_parse_legacy_enable_blocks_still_work(tmp_path):
    config = tmp_path / "test_items.txt"
    config.write_text(
        """
[lawdisk]
enable = yes
IGNORE_ERROR = yes

[filesystem]
enable = no
""",
        encoding="utf-8",
    )

    selected, params = parse_items_file(config)

    assert selected == ["lawdisk"]
    assert params["lawdisk"]["IGNORE_ERROR"] == "yes"


def test_run_single_item_omits_allure_args_without_plugin(monkeypatch):
    captured = {}

    def fake_pytest_main(args):
        captured["args"] = args
        return 0

    monkeypatch.setattr(nvme_raid_test.importlib.util, "find_spec", lambda name: None)
    monkeypatch.setattr(nvme_raid_test.pytest, "main", fake_pytest_main)

    assert nvme_raid_test.run_single_item("lawdisk", {}, clean_allure=True) == 0

    args = captured["args"]
    assert "--clean-alluredir" not in args
    assert not any(arg.startswith("--alluredir=") for arg in args)
    assert "--junitxml=report_lawdisk.xml" in args
