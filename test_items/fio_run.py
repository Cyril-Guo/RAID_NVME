"""Per-case FIO launch helpers. Each CI test supplies its own CSV and mode."""
import os
import sys
import subprocess
from datetime import datetime

import pytest

from test_items.case_paths import io_stress_dir, stress_monitor_dir
from test_items.fio_allure import (
    RESULT_SUMMARY_NAME,
    attach_case_fio_summary,
    attach_case_terminal_output,
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
    "verify failed",
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

# Hard stops must fail the case even when the shell wrongly returns 0
# (e.g. fio_cycle historically swallowed run_fio.sh rc). Soft/partial IO
# noise may still be ignored when ignore_fio_job_errors=True.
_HARD_FIO_FAILURE_MARKERS = (
    "FIO stage failed",
    "FIO stage abort",
    "MIX_FAIL_ON_ANY=yes, fail",
    "FIO failed:",
    "idle watchdog timeout",
    "test fail occur",
    "Refuse to run",
    "No non-system test disk found",
    "Fail to detect system disk",
)


def _is_machinecheck_line(line):
    return any(marker in line for marker in _MACHINECHECK_MARKERS)


def _is_hard_fio_failure_line(line):
    return any(marker in line for marker in _HARD_FIO_FAILURE_MARKERS)


def _is_fio_job_error_line(line):
    return any(marker in line for marker in _FIO_JOB_ERROR_MARKERS)


def collect_failure_lines(text, ignore_machinecheck=False, ignore_fio_job_errors=False):
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
        if _is_hard_fio_failure_line(line):
            lines.append(line)
            continue
        if ignore_fio_job_errors and _is_fio_job_error_line(line):
            continue
        if any(marker in line for marker in markers):
            lines.append(line)
    return lines


def resolve_fio_csv(item):
    name = os.environ.get("FIO_CONFIG", "").strip() or f"Input_Config_{item}.csv"
    name = os.path.basename(name.replace("\\", "/"))
    path = os.path.join(io_stress_dir(), name)
    if not os.path.isfile(path):
        pytest.fail(f"Missing FIO CSV for {item}: {path}")
    return name


def ignore_error_enabled():
    return os.environ.get("IGNORE_ERROR", "").strip().lower() == "yes"


def build_fio_args(mode, item, extra=None):
    flag_val = "NON-STOP" if ignore_error_enabled() else "STOP"
    args = ["-i", mode, "-f", flag_val, "-n", resolve_fio_csv(item)]
    if extra:
        args.extend(extra)
    fio_disks = os.environ.get("FIO_DISKS", "").strip()
    if fio_disks:
        args.extend(["-u", fio_disks])
    return args


def maybe_start_monitor():
    if os.environ.get("STRESS_MONITOR", "").strip().lower() != "yes":
        return
    monitor_dir = stress_monitor_dir()
    monitor_main = os.path.join(monitor_dir, "main.py")
    if not os.path.exists(monitor_main):
        return
    monitor_cmd = [sys.executable, monitor_main]
    runtime = os.environ.get("MONITOR_RUNTIME", "").strip()
    if runtime:
        monitor_cmd.extend(["-r", runtime])
    monitor_disks = os.environ.get("FIO_DISKS", "").strip()
    if monitor_disks:
        monitor_cmd.extend(["-d", monitor_disks])
    print(f"[{_ts()}] Start Stress_Monitor in background (Runtime: {runtime or 'Default'})...")
    subprocess.Popen(
        monitor_cmd,
        cwd=monitor_dir,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def run_and_check_fio(fio_args, extra_output=""):
    stress_dir = io_stress_dir()
    return run_and_check_argv(
        ["bash", "./Fio_All.sh"] + fio_args,
        cwd=stress_dir,
        extra_output=extra_output,
        use_result_log=True,
    )


def run_and_check_argv(argv, cwd, extra_output="", use_result_log=False, attach=True):
    ignore_error = ignore_error_enabled()
    cmd_str = " ".join(argv)
    print(f"{_ts()} [START] cwd={cwd} {cmd_str}")
    process = subprocess.Popen(
        argv,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        universal_newlines=True,
    )
    full_output = []
    for line in process.stdout:
        timed_line = f"[{_ts()}] {line}"
        print(timed_line, end="")
        full_output.append(timed_line)
    process.wait()
    exit_code = process.returncode
    output_text = extra_output + "".join(full_output)
    output_failures = collect_failure_lines(
        output_text,
        ignore_machinecheck=ignore_error,
        ignore_fio_job_errors=(exit_code == 0),
    )
    if attach or exit_code != 0 or output_failures:
        attach_case_terminal_output(output_text)
        attach_case_fio_summary(output_text)

    res_content = ""
    if use_result_log:
        result_log = os.path.join(cwd, "log", "ResultLog", "fio_result", "result.log")
        if os.path.exists(result_log):
            with open(result_log, "r") as handle:
                res_content = handle.read()
            attach_named_text(res_content, RESULT_SUMMARY_NAME)
    attach_machinecheck_records(
        cwd if use_result_log else io_stress_dir(),
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
    if use_result_log:
        result_failures = collect_failure_lines(
            res_content,
            ignore_machinecheck=ignore_error,
            ignore_fio_job_errors=(exit_code == 0),
        )
        if result_failures:
            pytest.fail("测试结果中检测到失败关键字:\n" + "\n".join(result_failures[:50]))
        if res_content and (not ignore_error) and "Fail" in res_content:
            pytest.fail("测试结果中检测到失败关键字:\n" + "\n".join(result_failures[:50] or ["Fail"]))
    print(f"{_ts()} [SUCCESS] {cmd_str}")
    return output_text
