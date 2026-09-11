"""Filesystem FIO stress（无 Input_Config CSV，模型由 fio.sh 内置生成）。"""
import os

import allure
import pytest

from test_items.fio_run import build_fio_args, maybe_start_monitor, run_and_check_fio


def _item_name(default: str = "test_ci_02_filesystem") -> str:
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
            f"FIO_RUNTIME must be >=180 and divisible by 180, got: {runtime_text}"
        )

    maybe_start_monitor()
    fio_args = build_fio_args("filesystemstress", item)
    allure.dynamic.title(f"FIO 测试: {item}（文件系统）")
    allure.dynamic.description(
        "每盘 16 分区、22 个 fio 模型、iodepth=4；"
        "每轮 180s 后切换读写混合与对齐权重；"
        f"共 {int(runtime_text) // 180} 轮，合计 {runtime_text}s。"
    )
    run_and_check_fio(fio_args)
