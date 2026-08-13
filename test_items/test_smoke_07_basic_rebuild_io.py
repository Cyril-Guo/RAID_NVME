import allure

from test_items.basic_io_common import (
    CommandLog,
    power_cycle_one_disk_per_group,
    prepare_basic_raid5_vds,
    prepare_physical_io_case,
    verify_all_vds_degraded,
)
from test_items import test_smoke_03_lawdisk as lawdisk_case


def test_basic_rebuild_io():
    allure.dynamic.title("Test_CI_basic_rebuild_IO")
    allure.dynamic.description(
        "Per-case prep (CSD clear / dpraid update / draid rmmod-insmod / VD-PD clear), "
        "create eight RAID5 VDs, drop one disk per group to degraded, then run lawdisk FIO."
    )

    log = CommandLog()
    try:
        log.write("Test_CI_basic_rebuild_IO phase: DUT refresh before case")
        prepare_physical_io_case(log)
        log.write("Test_CI_basic_rebuild_IO phase: prepare RAID5 VDs")
        _, groups, _ = prepare_basic_raid5_vds(log)
        log.write("Test_CI_basic_rebuild_IO phase: power-cycle one disk in each group before FIO")
        power_cycle_one_disk_per_group(groups, log)
        log.write("Test_CI_basic_rebuild_IO phase: verify degraded VDs")
        verify_all_vds_degraded(log, expected=8)
        log.write("Test_CI_basic_rebuild_IO phase: start lawdisk FIO on degraded VDs")
    finally:
        log.attach("Test_CI_basic_rebuild_IO_terminal_output")

    lawdisk_case.test_lawdiskstress()
