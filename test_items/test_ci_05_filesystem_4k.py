"""Filesystem FIO stress (4k)."""
import os

import allure
import pytest

from test_items.fio_run import build_fio_args, maybe_start_monitor, run_and_check_fio


def _item_name(default: str = "test_ci_05_filesystem_4k") -> str:
    return (os.environ.get("RAID_NVME_ITEM") or default).strip() or default


def test_filesystem_stress():
    item = _item_name()
    runtime_text = os.environ.get("FIO_RUNTIME", "").strip()
    if (
        not runtime_text.isdigit()
        or int(runtime_text) < 180
        or int(runtime_text) % 180 != 0
    ):
        pytest.fail(
            f"FIO_RUNTIME 必须是不小于 180 且能被 180 整除的秒数，当前值: {runtime_text}"
        )

    maybe_start_monitor()
    fio_args = build_fio_args("filesystemstress", item)
    allure.dynamic.title(f"FIO 测试: {item} random mixed IO")
    allure.dynamic.description(
        "每盘 16 分区，每分区同时运行 16 个不同 fio 模型，iodepth=32；"
        "每轮运行 180 秒，然后改变随机混合读写比例及对齐/非对齐权重；"
        f"共 {int(runtime_text) // 180} 轮，总 fio 时长 {runtime_text} 秒；模型={item}。"
    )
    run_and_check_fio(fio_args)
