from pathlib import Path

from nvme_raid_test import parse_items_file


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
