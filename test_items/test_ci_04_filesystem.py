"""
CI 测试 —— 文件系统(Filesystem)随机混合 FIO 压力测试。

每盘创建 16 个分区；每个分区同时运行 16 个不同模型、队列深度 32 的
fio 进程。每轮运行 180 秒，然后改变读写比例及对齐/非对齐权重，持续到总时长。
"""
import os

import allure
import pytest

from test_items.fio_run import build_fio_args, maybe_start_monitor, run_and_check_fio


def test_filesystemstress():
    runtime_text = os.environ.get("FIO_RUNTIME", "180").strip() or "180"
    if (
        not runtime_text.isdigit()
        or int(runtime_text) < 180
        or int(runtime_text) % 180 != 0
    ):
        pytest.fail(f"FIO_RUNTIME 必须是不小于 180 且能被 180 整除的秒数，当前值: {runtime_text}")

    maybe_start_monitor()
    fio_args = build_fio_args("filesystemstress", "filesystem")
    allure.dynamic.title("FIO 测试: filesystem random mixed IO")
    allure.dynamic.description(
        "每盘 16 分区，每分区同时运行 16 个不同 fio 模型，iodepth=32；"
        "每轮运行 180 秒，然后改变随机混合读写比例及对齐/非对齐权重；"
        f"共 {int(runtime_text) // 180} 轮，总 fio 时长 {runtime_text} 秒。"
    )
    run_and_check_fio(fio_args)
