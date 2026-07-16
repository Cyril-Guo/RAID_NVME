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
        "Create eight RAID5 VDs from non-system NVMe disks, power-cycle one disk in each group, "
        "verify degraded VDs, then run lawdisk FIO."
    )

    if os.environ.get("ALLOW_DESTRUCTIVE_FIO", "0") != "1":
        pytest.skip("ALLOW_DESTRUCTIVE_FIO is not enabled; skip destructive basic rebuild IO test")

    log = CommandLog()
    try:
        _, groups, _ = prepare_basic_raid5_vds(log)
        power_cycle_one_disk_per_group(groups, log)
        verify_all_vds_degraded(log, expected=8)
    finally:
        log.attach("Test_Smoke_07_basic_rebuild_IO_terminal_output")

    lawdisk_case.test_lawdiskstress()
