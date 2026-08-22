"""
Smoke 测试 —— 裸盘(Raw Disk)FIO 压力测试。

本用例使用 IO_Stress/Input_Config_lawdisk.csv，不调用其它用例。
"""
import allure

from test_items.fio_run import build_fio_args, maybe_start_monitor, run_and_check_fio


def test_lawdiskstress():
    maybe_start_monitor()
    fio_args = build_fio_args("lawdiskstress", "lawdisk")
    allure.dynamic.title("FIO 测试: lawdiskstress")
    allure.dynamic.description("裸盘 FIO 压力测试，使用 Input_Config_lawdisk.csv。")
    run_and_check_fio(fio_args)
