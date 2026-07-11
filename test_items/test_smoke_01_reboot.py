"""
Smoke 测试 —— Reboot 电源循环（重启）压力测试。

本用例完全自包含，不依赖任何共享辅助函数，读完本文件即可理解全部流程：
  1. 从环境变量（由 test_items.txt 注入）解析循环次数与错误处理策略；
  2. 按需在后台启动压力监控工具；
  3. 组装并以异步(setsid)方式触发 Fio_All.sh 的 reboot 流程。
     重启会中断 SSH，因此触发后立即返回，避免连接断开被误判为失败。
"""
import os
import sys
import subprocess
from datetime import datetime

import pytest
import allure


def _ts():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def test_reboot_powercycle():
    # ---------- 1. 解析运行参数（全部来自 test_items.txt 注入的环境变量）----------
    raw_cycles = os.environ.get("FIO_CYCLES", "").strip()
    try:
        loops = int(raw_cycles) if raw_cycles else 10
    except ValueError:
        loops = 10
    # IGNORE_ERROR=yes 表示忽略 MachineCheck 错误继续 -> 不停止
    ignore_error = os.environ.get("IGNORE_ERROR", "").strip().lower() == "yes"
    flag_val = "NON-STOP" if ignore_error else "STOP"

    # ---------- 2. 按需后台启动压力监控 ----------
    if os.environ.get("STRESS_MONITOR", "").strip().lower() == "yes":
        monitor_dir = os.path.join(os.path.dirname(__file__), "..", "Stress_Monitor")
        monitor_main = os.path.join(monitor_dir, "main.py")
        if os.path.exists(monitor_main):
            monitor_cmd = [sys.executable, monitor_main]
            runtime = os.environ.get("MONITOR_RUNTIME", "").strip()
            if runtime:
                monitor_cmd.extend(["-r", runtime])
            print(f"[{_ts()}] Start Stress_Monitor in background (Runtime: {runtime or 'Default'})...")
            subprocess.Popen(
                monitor_cmd, cwd=monitor_dir,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True,
            )

    # ---------- 3. 组装 Fio_All.sh 参数 ----------
    fio_args = ["-i", "reboot", "-l", str(loops), "-f", flag_val]
    fio_disks = os.environ.get("FIO_DISKS", "").strip()
    if fio_disks:
        fio_args.extend(["-u", fio_disks])

    # ---------- 4. Allure 报告标题与描述 ----------
    allure.dynamic.title(f"FIO 测试: reboot (循环 {loops} 次)")
    allure.dynamic.description(
        f"重启电源循环压力测试，循环 {loops} 次；"
        f"出现 MachineCheck 错误时{'不停止' if ignore_error else '停止'}。"
    )

    # ---------- 5. 破坏性写入权限开关 ----------
    if os.environ.get("ALLOW_DESTRUCTIVE_FIO", "0") != "1":
        pytest.skip("ALLOW_DESTRUCTIVE_FIO 未开启，跳过破坏性 IO 测试")

    # ---------- 6. 异步触发（重启会中断 SSH，触发后立即返回）----------
    io_stress_dir = os.path.join(os.path.dirname(__file__), "..", "IO_Stress")
    cmd_str = f"bash ./Fio_All.sh {' '.join(fio_args)}"
    with allure.step(f"异步触发 FIO 指令: {cmd_str}"):
        print(f"{_ts()} [START] {cmd_str}")
        print("检测到重启任务，采用异步(setsid)触发模式...")
        subprocess.Popen(
            f"setsid bash ./Fio_All.sh {' '.join(fio_args)} > /dev/null 2>&1 &",
            shell=True, cwd=io_stress_dir,
        )
        print("测试已触发，安全退出 SSH 以防重启导致连接中断报错。")
