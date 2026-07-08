"""
Smoke 测试 —— 清理与恢复(Restore)。

本用例完全自包含，不依赖任何共享辅助函数，读完本文件即可理解全部流程：
  1. 停止后台压力监控工具（发送 SIGINT 触发其生成报告）；
  2. 从环境变量（由 test_items.txt 注入）解析循环次数与错误处理策略；
  3. 组装并同步执行 Fio_All.sh 的 restore 流程，实时透传输出；
  4. 校验退出码与结果日志，判定用例成败。

注意：本项通常作为最后一个测试项执行，负责收尾清理并停止监控。
"""
import os
import subprocess
from datetime import datetime

import pytest
import allure


def _ts():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def test_cancel_restore():
    # ---------- 1. 停止后台压力监控并触发其生成报告 ----------
    try:
        print(f"[{_ts()}] 🛑 正在停止 Stress_Monitor_Tool 并生成报告...")
        # 发送 SIGINT(2)，等同 Ctrl+C；main.py 捕获后走 finally 生成报告
        subprocess.run(["pkill", "-2", "-f", "Stress_Monitor_Tool/main.py"], check=False)
    except Exception as e:
        print(f"[{_ts()}] ❌ 停止监控工具失败: {e}")

    # ---------- 2. 解析运行参数（全部来自 test_items.txt 注入的环境变量）----------
    raw_cycles = os.environ.get("FIO_CYCLES", "").strip()
    try:
        loops = int(raw_cycles) if raw_cycles else 10
    except ValueError:
        loops = 10
    # IGNORE_ERROR=true 表示忽略 MachineCheck 错误继续 -> 不停止
    ignore_error = os.environ.get("IGNORE_ERROR", "").strip().lower() == "true"
    flag_val = "NON-STOP" if ignore_error else "STOP"

    # ---------- 3. 组装 Fio_All.sh 参数 ----------
    fio_args = ["-i", "restore", "-l", str(loops), "-f", flag_val]
    fio_disks = os.environ.get("FIO_DISKS", "").strip()
    if fio_disks:
        fio_args.extend(["-u", fio_disks])

    # ---------- 4. Allure 报告标题与描述 ----------
    allure.dynamic.title("FIO 测试: restore (清理与恢复)")
    allure.dynamic.description("停止后台监控并执行清理/恢复流程，收尾整个测试。")

    # ---------- 5. 破坏性写入权限开关 ----------
    if os.environ.get("ALLOW_DESTRUCTIVE_FIO", "0") != "1":
        pytest.skip("ALLOW_DESTRUCTIVE_FIO 未开启，跳过破坏性 IO 测试")

    # ---------- 6. 同步执行并实时透传输出 ----------
    io_stress_dir = os.path.join(os.path.dirname(__file__), "test_items", "IO_Stress")
    cmd_str = f"bash ./Fio_All.sh {' '.join(fio_args)}"
    with allure.step(f"执行 FIO 指令: {cmd_str}"):
        print(f"{_ts()} [START] {cmd_str}")
        process = subprocess.Popen(
            ["bash", "./Fio_All.sh"] + fio_args,
            cwd=io_stress_dir,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, universal_newlines=True,
        )
        full_output = []
        for line in process.stdout:
            timed_line = f"[{_ts()}] {line}"
            print(timed_line, end="")
            full_output.append(timed_line)
        process.wait()
        exit_code = process.returncode

        allure.attach(
            "".join(full_output), name="终端完整输出",
            attachment_type=allure.attachment_type.TEXT,
        )
        if exit_code != 0:
            print(f"{_ts()} [ERROR] 脚本执行失败，退出码: {exit_code}")
            pytest.fail(f"FIO 脚本执行失败，返回码: {exit_code}")
        print(f"{_ts()} [SUCCESS] 脚本执行完成")

    # ---------- 7. 结果汇总 ----------
    result_log = os.path.join(io_stress_dir, "log", "ResultLog", "result.log")
    if os.path.exists(result_log):
        with open(result_log, "r") as f:
            res_content = f.read()
        allure.attach(res_content, name="测试结果汇总", attachment_type=allure.attachment_type.TEXT)
        if "Fail" in res_content:
            pytest.fail("测试结果中检测到失败关键字")
