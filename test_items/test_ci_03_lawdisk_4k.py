"""Lawdisk FIO stress (4k)."""
import os

import allure

from test_items.fio_run import build_fio_args, maybe_start_monitor, run_and_check_fio


def _item_name(default: str = "lawdisk_4k") -> str:
    return (os.environ.get("RAID_NVME_ITEM") or default).strip() or default


def test_lawdisk_stress():
    item = _item_name()
    maybe_start_monitor()
    fio_args = build_fio_args("lawdiskstress", item)
    allure.dynamic.title(f"FIO 测试: {item} (裸盘)")
    allure.dynamic.description(
        f"裸盘 FIO；对齐模型 {item} / FIO_CONFIG={os.environ.get('FIO_CONFIG', '')}。"
    )
    run_and_check_fio(fio_args)
