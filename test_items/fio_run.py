"""FIO helpers for PowerCycle cases (CSV resolve + arg build + log scanners)."""
import os
from datetime import datetime

import pytest

from test_items.case_paths import io_stress_dir


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

# Hard stops must fail even when the shell wrongly returns 0.
_HARD_FIO_FAILURE_MARKERS = (
    "FIO stage failed",
    "FIO stage abort",
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
