"""
Smoke 测试 —— 文件系统(Filesystem)FIO 压力测试。

本用例使用 IO_Stress/Input_Config_filesystem.csv，不调用其它用例。
"""
import allure

from test_items.fio_run import build_fio_args, maybe_start_monitor, run_and_check_fio


def test_filesystemstress():
    maybe_start_monitor()
    fio_args = build_fio_args("filesystemstress", "filesystem")
    allure.dynamic.title("FIO 测试: filesystemstress")
    allure.dynamic.description("文件系统 FIO 压力测试，使用 Input_Config_filesystem.csv。")
    run_and_check_fio(fio_args)
