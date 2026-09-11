"""FIO helpers for PowerCycle cases (arg build + log scanners)."""
import os
from datetime import datetime

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


def _ts():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


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


def ignore_error_enabled():
    return os.environ.get("IGNORE_ERROR", "").strip().lower() == "yes"


def build_fio_args(mode, item, extra=None):
    """Build powercycle_direct.sh args.

    FIO models come from powercycle_random.py (powercycle_auto.csv) at runtime;
    no static Input_Config CSV is passed.
    """
    del item  # reserved for call-site clarity; plan generator uses mode/item env
    flag_val = "NON-STOP" if ignore_error_enabled() else "STOP"
    args = ["-i", mode, "-f", flag_val]
    if extra:
        args.extend(extra)
    fio_disks = os.environ.get("FIO_DISKS", "").strip()
    if fio_disks:
        args.extend(["-u", fio_disks])
    return args
