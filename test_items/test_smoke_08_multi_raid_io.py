import os

import allure
import pytest

from test_items.basic_io_common import CommandLog, prepare_multi_raid_vds
from test_items import test_smoke_03_lawdisk as lawdisk_case


def test_multi_raid_io():
    allure.dynamic.title("Test_Smoke_08_multi_raid_IO")
    allure.dynamic.description(
        "Create RAID0 (1/2 disks), RAID1 (2 disks), RAID10 (4 disks), and RAID50 (6 disks), "
        "create four VDs per drive group, then run 1min bssplit mixed IO plus 4x25s lawdisk FIO."
    )

    if os.environ.get("ALLOW_DESTRUCTIVE_FIO", "0") != "1":
        pytest.skip("ALLOW_DESTRUCTIVE_FIO is not enabled; skip destructive multi-RAID IO test")

    log = CommandLog()
    try:
        log.write("Test_Smoke_08_multi_raid_IO phase: prepare multi-RAID VDs")
        prepare_multi_raid_vds(log)
        log.write("Test_Smoke_08_multi_raid_IO phase: start bssplit 1min + 4x25s lawdisk FIO")
    finally:
        log.attach("Test_Smoke_08_multi_raid_IO_terminal_output")

    lawdisk_case.test_lawdiskstress()
