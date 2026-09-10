"""Basic RAID5 IO (4k)."""
import os

import allure

from test_items.basic_io_common import CommandLog, prepare_basic_raid5_vds
from test_items.fio_run import build_fio_args, maybe_start_monitor, run_and_check_fio


def _item_name(default: str = "basic_io_4k") -> str:
    return (os.environ.get("RAID_NVME_ITEM") or default).strip() or default


def test_basic_io():
    item = _item_name()
    allure.dynamic.title(f"Test_CI_{item}")
    allure.dynamic.description(
        f"Create eight RAID5 VDs and run FIO_CONFIG for {item} on healthy VDs. "
        "Requires env_prepare beforehand."
    )

    log = CommandLog()
    try:
        log.write(f"{item} phase: prepare RAID5 VDs")
        prepare_basic_raid5_vds(log)
        log.write(f"{item} phase: start FIO")
    finally:
        prefix = "\n".join(log.lines) + "\n"

    maybe_start_monitor()
    run_and_check_fio(build_fio_args("lawdiskstress", item), extra_output=prefix)
