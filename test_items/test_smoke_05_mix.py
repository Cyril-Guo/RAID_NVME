"""
Smoke 测试 —— 混合 IO(Mixed IO)FIO 压力测试。

本用例完全自包含，不依赖任何共享辅助函数，读完本文件即可理解全部流程：
  1. 从环境变量（由 test_items.txt 注入）解析错误处理策略；
  2. 按需在后台启动压力监控工具；
  3. 组装并同步执行 Fio_All.sh 的 lawdiskstress 流程（追加 --mix_io yes 启用混合读写），
     实时透传输出；
  4. 校验退出码与结果日志，判定用例成败。
"""
import os
import sys
import subprocess
from datetime import datetime

import pytest
import allure


def _ts():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _collect_failure_lines(text):
    markers = (
        "FIO command failed",
        "FIO stage failed",
        "MachineCheck inconsistencies found",
        "ERROR: MachineCheck",
        "test fail occur",
    )
    return [line.strip() for line in text.splitlines() if any(marker in line for marker in markers)]


def test_mix_stress():
    # ---------- 1. 解析运行参数（全部来自 test_items.txt 注入的环境变量）----------
    # 说明：压测项的循环由 IO_Stress 的 CSV 配置与 runtime 决定，
    # 底层 Fio_All.sh 会将 LOOP 固定为 1，故此处不再使用 FIO_CYCLES。
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

    # ---------- 3. 组装 Fio_All.sh 参数（混合 IO 模式追加 --mix_io yes）----------
    fio_args = ["-i", "lawdiskstress", "-f", flag_val, "--mix_io", "yes"]
    fio_disks = os.environ.get("FIO_DISKS", "").strip()
    if fio_disks:
        fio_args.extend(["-u", fio_disks])

    # ---------- 4. Allure 报告标题与描述 ----------
    allure.dynamic.title("FIO 测试: mix (混合 IO)")
    allure.dynamic.description(
        f"混合读写 FIO 压力测试；"
        f"出现 MachineCheck 错误时{'不停止' if ignore_error else '停止'}。"
    )

    # ---------- 5. 破坏性写入权限开关 ----------
    if os.environ.get("ALLOW_DESTRUCTIVE_FIO", "0") != "1":
        pytest.skip("ALLOW_DESTRUCTIVE_FIO 未开启，跳过破坏性 IO 测试")

    # ---------- 6. 同步执行并实时透传输出 ----------
    io_stress_dir = os.path.join(os.path.dirname(__file__), "..", "IO_Stress")
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
        output_text = "".join(full_output)
        output_failures = _collect_failure_lines(output_text)

        allure.attach(
            output_text, name="终端完整输出",
            attachment_type=allure.attachment_type.TEXT,
        )
        if exit_code != 0:
            print(f"{_ts()} [ERROR] 脚本执行失败，退出码: {exit_code}")
            pytest.fail(f"FIO 脚本执行失败，返回码: {exit_code}")
        if output_failures:
            pytest.fail("FIO 输出中检测到失败关键字:\n" + "\n".join(output_failures[:10]))
        print(f"{_ts()} [SUCCESS] 脚本执行完成")

    # ---------- 7. 结果汇总 ----------
    result_log = os.path.join(io_stress_dir, "log", "ResultLog", "result.log")
    if os.path.exists(result_log):
        with open(result_log, "r") as f:
            res_content = f.read()
        allure.attach(res_content, name="测试结果汇总", attachment_type=allure.attachment_type.TEXT)
        result_failures = _collect_failure_lines(res_content)
        if "Fail" in res_content or result_failures:
            pytest.fail("测试结果中检测到失败关键字:\n" + "\n".join(result_failures[:10] or ["Fail"]))
