import allure

from test_items.basic_io_common import CommandLog, prepare_basic_raid5_vds
from test_items.fio_run import build_fio_args, maybe_start_monitor, run_and_check_fio


def test_basic_io():
    allure.dynamic.title("Test_CI_basic_IO")
    allure.dynamic.description(
        "Create eight RAID5 VDs and run Input_Config_basic_io.csv on healthy VDs. "
        "Requires env_prepare to have refreshed dpraid/draid beforehand."
    )

    log = CommandLog()
    try:
        log.write("Test_CI_basic_IO phase: prepare RAID5 VDs")
        prepare_basic_raid5_vds(log)
        log.write("Test_CI_basic_IO phase: start FIO with Input_Config_basic_io.csv")
    finally:
        prefix = "\n".join(log.lines) + "\n"

    maybe_start_monitor()
    run_and_check_fio(build_fio_args("lawdiskstress", "basic_io"), extra_output=prefix)
