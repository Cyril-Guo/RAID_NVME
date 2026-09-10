"""Basic rebuild IO (512)."""
import os

import allure

from test_items.basic_io_common import (
    CommandLog,
    power_cycle_one_disk_per_group,
    prepare_basic_raid5_vds,
    verify_all_vds_degraded,
)
from test_items.fio_run import build_fio_args, maybe_start_monitor, run_and_check_fio


def _item_name(default: str = "test_ci_12_basic_rebuild_io_512") -> str:
    return (os.environ.get("RAID_NVME_ITEM") or default).strip() or default


def test_basic_rebuild_io():
    item = _item_name()
    allure.dynamic.title(f"Test_CI_{item}")
    allure.dynamic.description(
        f"Create eight RAID5 VDs, degrade one disk/group, run FIO for {item}. "
        "Requires env_prepare beforehand."
    )

    log = CommandLog()
    try:
        log.write(f"{item} phase: prepare RAID5 VDs")
        _, groups, _ = prepare_basic_raid5_vds(log)
        log.write(f"{item} phase: power-cycle one disk in each group before FIO")
        power_cycle_one_disk_per_group(groups, log)
        log.write(f"{item} phase: verify degraded VDs")
        verify_all_vds_degraded(log, expected=8)
        log.write(f"{item} phase: start FIO")
    finally:
        prefix = "\n".join(log.lines) + "\n"

    maybe_start_monitor()
    run_and_check_fio(
        build_fio_args("lawdiskstress", item),
        extra_output=prefix,
    )
