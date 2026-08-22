"""
Smoke 测试 —— 混合 IO(Mixed IO)FIO 压力测试。

本用例独立执行：lawdiskstress + --mix_io yes，由 random_choice.py 生成 4 路 MixIO 任务。
MIX_FAIL_ON_ANY=no：FIO/盘错误只记录，测试继续。IOPS 跌 0 不算失败。
MIX_FAIL_ON_ANY=yes：任何 FIO 报错或非 0 退出都算测试失败。
"""
import os

import allure

from test_items.fio_run import build_fio_args, maybe_start_monitor, run_and_check_fio


def test_mix_stress():
    maybe_start_monitor()
    fio_args = build_fio_args("lawdiskstress", "mix", extra=["--mix_io", "yes"])
    fail_on_any = os.environ.get("MIX_FAIL_ON_ANY", "no").strip().lower()
    allure.dynamic.title("FIO 测试: mix (混合 IO)")
    allure.dynamic.description(
        f"混合读写 FIO 压力测试；4 路 MixIO 由 random_choice.py 生成。"
        f" MIX_FAIL_ON_ANY={fail_on_any or 'no'}。"
    )
    print(f"[MIX] MIX_FAIL_ON_ANY={fail_on_any or 'no'}")
    run_and_check_fio(fio_args)
