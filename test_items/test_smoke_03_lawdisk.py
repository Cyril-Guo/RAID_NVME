"""
Smoke 测试 —— 裸盘(Raw Disk)FIO 压力测试。

本用例完全自包含，不依赖任何共享辅助函数，读完本文件即可理解全部流程：
  1. 从环境变量（由 test_items.txt 注入）解析错误处理策略；
  2. 按需在后台启动压力监控工具；
  3. 组装并同步执行 Fio_All.sh 的 lawdiskstress 流程，实时透传输出；
  4. 校验退出码与结果日志，判定用例成败。
"""
import os
import sys
import subprocess
from datetime import datetime

import pytest
import allure

from test_items.case_paths import io_stress_dir, stress_monitor_dir
from test_items.fio_allure import (
    RESULT_SUMMARY_NAME,
    attach_machinecheck_records,
    attach_named_text,
)


def _ts():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


_MACHINECHECK_MARKERS = (
    "MachineCheck inconsistencies found",
    "ERROR: MachineCheck",
    "MachineCheck Log Inconsistency",
    "Whitelist field differences",
)

_FAILURE_MARKERS = (
    "FIO command failed",
    "FIO stage failed",
    "FIO stage abort",
    "FIO failed",
    "Fail to detect system disk",
    "Refuse to run",
    "No non-system test disk found",
    "test fail occur",
    "idle watchdog timeout",
    "----- FIO error detail",
    "fio:",
    "io_u error",
    "err=",
    "Invalid argument",
    "direct IO errored",
)


_FIO_JOB_ERROR_MARKERS = (
    "FIO command failed",
    "FIO stage failed",
    "FIO stage abort",
    "FIO failed",
    "----- FIO error detail",
    "fio:",
    "io_u error",
    "err=",
    "Invalid argument",
    "direct IO errored",
)


def _is_machinecheck_line(line):
    return any(marker in line for marker in _MACHINECHECK_MARKERS)


def _is_fio_job_error_line(line):
    return any(marker in line for marker in _FIO_JOB_ERROR_MARKERS)


def _collect_failure_lines(text, ignore_machinecheck=False, ignore_fio_job_errors=False):
    markers = _FAILURE_MARKERS
    if not ignore_machinecheck:
        markers = _FAILURE_MARKERS + _MACHINECHECK_MARKERS
    lines = []
    in_detail = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if "----- FIO error detail begin" in line:
            in_detail = True
            if not ignore_fio_job_errors:
                lines.append(line)
            continue
        if "----- FIO error detail end" in line:
            if not ignore_fio_job_errors:
                lines.append(line)
            in_detail = False
            continue
        if in_detail:
            if not ignore_fio_job_errors:
                lines.append(line)
            continue
        if ignore_machinecheck and _is_machinecheck_line(line):
            continue
        if ignore_fio_job_errors and _is_fio_job_error_line(line):
            continue
        if any(marker in line for marker in markers):
            lines.append(line)
    return lines


def _collect_machinecheck_lines(text):
    return [line.strip() for line in text.splitlines() if line.strip() and _is_machinecheck_line(line)]


def _record_machinecheck_only(text, ignore_error):
    attach_machinecheck_records(io_stress_dir(), text=text, ignore_error=ignore_error)


def test_lawdiskstress():
    # ---------- 1. 解析运行参数（全部来自 test_items.txt 注入的环境变量）----------
    # 说明：压测项的循环由 IO_Stress 的 CSV 配置与 runtime 决定，
    # 底层 Fio_All.sh 会将 LOOP 固定为 1，故此处不再使用 FIO_CYCLES。
    # IGNORE_ERROR=yes：MachineCheck 仍记录，但不判失败；no：记录并判失败
    ignore_error = os.environ.get("IGNORE_ERROR", "").strip().lower() == "yes"
    flag_val = "NON-STOP" if ignore_error else "STOP"

    # ---------- 2. 按需后台启动压力监控 ----------
    if os.environ.get("STRESS_MONITOR", "").strip().lower() == "yes":
        monitor_dir = stress_monitor_dir()
        monitor_main = os.path.join(monitor_dir, "main.py")
        if os.path.exists(monitor_main):
            monitor_cmd = [sys.executable, monitor_main]
            runtime = os.environ.get("MONITOR_RUNTIME", "").strip()
            if runtime:
                monitor_cmd.extend(["-r", runtime])
            monitor_disks = os.environ.get("FIO_DISKS", "").strip()
            if monitor_disks:
                monitor_cmd.extend(["-d", monitor_disks])
            print(f"[{_ts()}] Start Stress_Monitor in background (Runtime: {runtime or 'Default'})...")
            subprocess.Popen(
                monitor_cmd, cwd=monitor_dir,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True,
            )

    # ---------- 3. 组装 Fio_All.sh 参数 ----------
    fio_args = ["-i", "lawdiskstress", "-f", flag_val]
    fio_disks = os.environ.get("FIO_DISKS", "").strip()
    if fio_disks:
        fio_args.extend(["-u", fio_disks])

    # ---------- 4. Allure 报告标题与描述 ----------
    allure.dynamic.title("FIO 测试: lawdiskstress")
    allure.dynamic.description(
        f"裸盘 FIO 压力测试；"
        f"出现 MachineCheck 差异时始终记录；{'不判失败' if ignore_error else '判失败并停止'}。"
    )

    # ---------- 5. 同步执行并实时透传输出 ----------
    stress_dir = io_stress_dir()
    cmd_str = f"bash ./Fio_All.sh {' '.join(fio_args)}"
    print(f"{_ts()} [START] cwd={stress_dir} {cmd_str}")
    process = subprocess.Popen(
        ["bash", "./Fio_All.sh"] + fio_args,
        cwd=stress_dir,
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
    output_failures = _collect_failure_lines(
        output_text,
        ignore_machinecheck=ignore_error,
        ignore_fio_job_errors=(exit_code == 0),
    )

    res_content = ""
    result_log = os.path.join(stress_dir, "log", "ResultLog", "fio_result", "result.log")
    if os.path.exists(result_log):
        with open(result_log, "r") as f:
            res_content = f.read()
        attach_named_text(res_content, RESULT_SUMMARY_NAME)
    attach_machinecheck_records(
        stress_dir,
        text=output_text + "\n" + res_content,
        ignore_error=ignore_error,
    )

    if exit_code != 0:
        print(f"{_ts()} [ERROR] 脚本执行失败，退出码: {exit_code}")
        detail = ""
        if output_failures:
            detail = "\n" + "\n".join(output_failures[:50])
        pytest.fail(f"FIO 脚本执行失败，返回码: {exit_code}{detail}")
    if output_failures:
        pytest.fail("FIO 输出中检测到失败关键字:\n" + "\n".join(output_failures[:50]))
    result_failures = _collect_failure_lines(
        res_content,
        ignore_machinecheck=ignore_error,
        ignore_fio_job_errors=(exit_code == 0),
    )
    if result_failures:
        pytest.fail("测试结果中检测到失败关键字:\n" + "\n".join(result_failures[:50]))
    if res_content and (not ignore_error) and "Fail" in res_content:
        pytest.fail("测试结果中检测到失败关键字:\n" + "\n".join(result_failures[:50] or ["Fail"]))
    print(f"{_ts()} [SUCCESS] 脚本执行完成")
