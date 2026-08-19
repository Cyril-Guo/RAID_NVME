import allure

from test_items.basic_io_common import (
    CommandLog,
    power_cycle_one_disk_per_group,
    prepare_basic_raid5_vds,
    prepare_physical_io_case,
    verify_all_vds_degraded,
)
from test_items.fio_run import build_fio_args, maybe_start_monitor, run_and_check_fio


def test_basic_rebuild_io():
    allure.dynamic.title("Test_CI_basic_rebuild_IO")
    allure.dynamic.description(
        "Per-case prep (dpraid update / draid rmmod-insmod / VD-PD clear), "
        "create eight RAID5 VDs, drop one disk per group to degraded, "
        "then run Input_Config_basic_rebuild_io.csv."
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
        log.write("Test_CI_basic_rebuild_IO phase: start FIO with Input_Config_basic_rebuild_io.csv")
    finally:
        prefix = "\n".join(log.lines) + "\n"

    maybe_start_monitor()
    run_and_check_fio(
        build_fio_args("lawdiskstress", "basic_rebuild_io"),
        extra_output=prefix,
    )
