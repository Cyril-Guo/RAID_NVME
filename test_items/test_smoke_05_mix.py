"""
Smoke 测试 —— 混合 IO(Mixed IO)FIO 压力测试。

本用例独立执行：lawdiskstress + --mix_io yes，由 random_choice.py 生成 4 路 MixIO 任务。
"""
import allure

from test_items.fio_run import build_fio_args, maybe_start_monitor, run_and_check_fio


def test_mix_stress():
    maybe_start_monitor()
    fio_args = build_fio_args("lawdiskstress", "mix", extra=["--mix_io", "yes"])
    allure.dynamic.title("FIO 测试: mix (混合 IO)")
    allure.dynamic.description("混合读写 FIO 压力测试；4 路 MixIO 由 random_choice.py 生成。")
    run_and_check_fio(fio_args)
