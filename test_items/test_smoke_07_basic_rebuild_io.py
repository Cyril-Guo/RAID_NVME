import os

import allure
import pytest

from test_items.basic_io_common import (
    CommandLog,
    power_cycle_one_disk_per_group,
    prepare_basic_raid5_vds,
    verify_all_vds_degraded,
)
from test_items import test_smoke_03_lawdisk as lawdisk_case


def test_basic_rebuild_io():
    allure.dynamic.title("Test_Smoke_07_basic_rebuild_IO")
    allure.dynamic.description(
        "Format non-system NVMe disks, add them as PDs, create eight RAID5 VDs, power-cycle one "
        "disk in each group, verify degraded VDs, then run lawdisk FIO."
    )

    if os.environ.get("ALLOW_DESTRUCTIVE_FIO", "0") != "1":
        pytest.skip("ALLOW_DESTRUCTIVE_FIO is not enabled; skip destructive basic rebuild IO test")

    log = CommandLog()
    try:
        log.write("Test_Smoke_07_basic_rebuild_IO phase: prepare RAID5 VDs")
        _, groups, _ = prepare_basic_raid5_vds(log)
        log.write("Test_Smoke_07_basic_rebuild_IO phase: power-cycle one disk in each group before FIO")
        power_cycle_one_disk_per_group(groups, log)
        log.write("Test_Smoke_07_basic_rebuild_IO phase: verify degraded VDs")
        verify_all_vds_degraded(log, expected=8)
        log.write("Test_Smoke_07_basic_rebuild_IO phase: start lawdisk FIO on degraded VDs")
    finally:
        log.attach("Test_Smoke_07_basic_rebuild_IO_terminal_output")

    lawdisk_case.test_lawdiskstress()
