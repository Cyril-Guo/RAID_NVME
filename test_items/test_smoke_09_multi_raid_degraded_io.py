import os

import allure
import pytest

from test_items.basic_io_common import (
    CommandLog,
    degrade_non_raid0_groups,
    expected_degraded_vd_count,
    prepare_multi_raid_vds,
    verify_all_vds_degraded,
)
from test_items import test_smoke_03_lawdisk as lawdisk_case


def test_multi_raid_degraded_io():
    allure.dynamic.title("Test_Smoke_09_multi_raid_degraded_IO")
    allure.dynamic.description(
        "Create RAID0/1/10/50 VDs, power-cycle one disk in each non-RAID0 group to degrade, "
        "verify degraded VDs, then run 1min bssplit mixed IO plus 4x25s lawdisk FIO."
    )

    if os.environ.get("ALLOW_DESTRUCTIVE_FIO", "0") != "1":
        pytest.skip("ALLOW_DESTRUCTIVE_FIO is not enabled; skip destructive multi-RAID degraded IO test")

    log = CommandLog()
    try:
        log.write("Test_Smoke_09_multi_raid_degraded_IO phase: prepare multi-RAID VDs")
        _, group_specs, _ = prepare_multi_raid_vds(log)
        log.write("Test_Smoke_09_multi_raid_degraded_IO phase: degrade non-RAID0 groups before FIO")
        degrade_non_raid0_groups(group_specs, log)
        log.write("Test_Smoke_09_multi_raid_degraded_IO phase: verify degraded VDs")
        verify_all_vds_degraded(log, expected=expected_degraded_vd_count(group_specs))
        log.write("Test_Smoke_09_multi_raid_degraded_IO phase: start bssplit 1min + 4x25s lawdisk FIO on degraded VDs")
    finally:
        log.attach("Test_Smoke_09_multi_raid_degraded_IO_terminal_output")

    lawdisk_case.test_lawdiskstress()
