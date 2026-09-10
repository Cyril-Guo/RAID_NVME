import os

import allure

from test_items.basic_io_common import CommandLog, run_env_prepare


def _item_name(default: str = "test_ci_00_env_prepare") -> str:
    return (os.environ.get("RAID_NVME_ITEM") or default).strip() or default


def test_env_prepare():
    item = _item_name()
    allure.dynamic.title(item)
    allure.dynamic.description(
        "Physical DUT environment prepare (CI physical parity): "
        "stop QEMU if running, unload draid, return vfio devices to host, "
        "install dpraid, rebuild draid, SMOKE 5-step CSD flash clear "
        "(rmmod/insmod/FORCE clear/rmmod/insmod), restore VD/PD."
    )

    log = CommandLog()
    try:
        log.write(f"{item} phase: run CI physical env prepare")
        run_env_prepare(log)
        log.write(f"{item} phase: done")
    finally:
        log.attach(f"{item}_commands")
