"""
Smoke 测试 —— DC 电源循环（掉电）压力测试。

本用例完全自包含，不依赖任何共享辅助函数，读完本文件即可理解全部流程：
  1. 从环境变量（由 test_items.txt 注入）解析循环次数与错误处理策略；
  2. 组装并以异步(setsid)方式触发 powercycle_direct.sh 的 dc 流程。
     掉电会中断 SSH，因此本用例只验证到达 request start；
     Jenkins 侧 ci/wait_powercycle_completion.sh 负责多圈完成闭环。
"""
import os
from datetime import datetime

import allure

from test_items.case_paths import io_stress_dir
from test_items.powercycle_launch import trigger_background_fio


def _ts():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def test_dc_powercycle():
    # ---------- 1. 解析运行参数（全部来自 test_items.txt 注入的环境变量）----------
    raw_cycles = os.environ.get("FIO_CYCLES", "").strip()
    try:
        loops = int(raw_cycles) if raw_cycles else 10
    except ValueError:
        loops = 10
    # IGNORE_ERROR=yes 表示忽略 MachineCheck 错误继续 -> 不停止
    ignore_error = os.environ.get("IGNORE_ERROR", "").strip().lower() == "yes"
    flag_val = "NON-STOP" if ignore_error else "STOP"

    # ---------- 2. 组装 Fio_All.sh 参数 ----------
    fio_args = ["-i", "dc", "-l", str(loops), "-f", flag_val]
    fio_disks = os.environ.get("FIO_DISKS", "").strip()
    if fio_disks:
        fio_args.extend(["-u", fio_disks])

    # ---------- 3. Allure 报告标题与描述 ----------
    allure.dynamic.title(f"FIO 测试: dc (循环 {loops} 次)")
    allure.dynamic.description(
        f"掉电电源循环压力测试，循环 {loops} 次；"
        f"出现 MachineCheck 错误时{'不停止' if ignore_error else '停止'}。"
    )

    # ---------- 5. 异步触发（掉电会中断 SSH，触发后立即返回）----------
    stress_dir = io_stress_dir()
    cmd_str = f"bash ./powercycle_direct.sh {' '.join(fio_args)}"
    with allure.step(f"异步触发 FIO 指令: {cmd_str}"):
        print(f"{_ts()} [START] cwd={stress_dir} {cmd_str}")
        print("检测到掉电任务，采用异步(setsid)触发模式...")
        trigger_background_fio(stress_dir, "dc", fio_args)
        print("测试已触发（request start）；多圈完成由 Jenkins wait_powercycle_completion 闭环。")
