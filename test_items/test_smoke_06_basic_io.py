import allure

from test_items.basic_io_common import CommandLog, prepare_basic_raid5_vds, prepare_physical_io_case
from test_items import test_smoke_03_lawdisk as lawdisk_case


def test_basic_io():
    allure.dynamic.title("Test_CI_basic_IO")
    allure.dynamic.description(
        "Per-case prep (CSD clear / dpraid update / draid rmmod-insmod / VD-PD clear), "
        "then create eight RAID5 VDs and run lawdisk FIO on healthy VDs."
    )

    log = CommandLog()
    try:
        log.write("Test_CI_basic_IO phase: DUT refresh before case")
        prepare_physical_io_case(log)
        log.write("Test_CI_basic_IO phase: prepare RAID5 VDs")
        prepare_basic_raid5_vds(log)
        log.write("Test_CI_basic_IO phase: start lawdisk FIO")
    finally:
        log.attach("Test_CI_basic_IO_terminal_output")

    lawdisk_case.test_lawdiskstress()
