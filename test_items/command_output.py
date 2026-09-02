"""Reliable command output capture for long-running storage tests."""
import os
import re
import shlex
import sys
from datetime import datetime


def timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def safe_console_write(text, stream=None):
    """Best-effort console mirror; a closed outer pipe must not abort the test."""
    target = stream or sys.stdout
    try:
        target.write(text)
        target.flush()
        return True
    except (BrokenPipeError, OSError, ValueError):
        return False


def safe_console_print(text):
    return safe_console_write(f"{text}\n")


def _safe_token(value):
    return re.sub(r"[^A-Za-z0-9._-]", "_", str(value or "unknown"))


def command_output_log_path(cwd):
    case_root = os.environ.get("RAID_NVME_CASE_ROOT", "").strip() or cwd
    run_key = os.environ.get("RAID_NVME_RUN_KEY", "").strip() or "fio"
    return os.path.join(os.path.abspath(case_root), f"fio_command_output_{_safe_token(run_key)}.log")


class CommandOutputCapture:
    """Persist output first and mirror it to stdout only as a secondary channel."""

    def __init__(self, cwd, argv, extra_output=""):
        self.cwd = os.path.abspath(cwd)
        self.command = shlex.join([str(arg) for arg in argv])
        self.extra_output = extra_output or ""
        self.parts = []
        self.console_available = True
        self.path = command_output_log_path(cwd)
        self._handle = None
        self._open_log()
        self.record(f"\n===== FIO command begin {timestamp()} =====\n", mirror=False)
        self.record(f"cwd={self.cwd}\n", mirror=False)
        self.record(f"command={self.command}\n", mirror=False)
        self.record(f"[{timestamp()}] [START] {self.command}\n")

    def _open_log(self):
        try:
            existed = os.path.exists(self.path) and os.path.getsize(self.path) > 0
            self._handle = open(self.path, "a", encoding="utf-8", buffering=1)
            if self.extra_output and not existed:
                self._handle.write(self.extra_output)
                self._handle.flush()
        except OSError as exc:
            self._handle = None
            self.path = ""
            self.parts.append(
                f"[{timestamp()}] [CAPTURE_WARN] cannot open persistent command log: {exc}\n"
            )

    def _persist(self, text):
        if self._handle is None:
            return
        try:
            self._handle.write(text)
            self._handle.flush()
        except OSError as exc:
            self.parts.append(
                f"[{timestamp()}] [CAPTURE_WARN] persistent command log write failed: {exc}\n"
            )
            try:
                self._handle.close()
            except OSError:
                pass
            self._handle = None
            self.path = ""

    def record(self, text, mirror=True):
        self.parts.append(text)
        self._persist(text)
        if mirror and self.console_available and not safe_console_write(text):
            self.console_available = False
            warning = (
                f"[{timestamp()}] [CONSOLE_WARN] stdout pipe closed; "
                "continue capturing command output in the local log.\n"
            )
            self.parts.append(warning)
            self._persist(warning)

    def record_child_line(self, line):
        self.record(f"[{timestamp()}] {line}")

    def finish(self, exit_code, elapsed_seconds):
        self.record(
            f"[{timestamp()}] [EXIT] rc={exit_code} elapsed={elapsed_seconds:.1f}s "
            f"console_mirror={'available' if self.console_available else 'closed'}\n",
            mirror=self.console_available,
        )
        self.record(f"===== FIO command end {timestamp()} =====\n", mirror=False)

    def output_text(self):
        return self.extra_output + "".join(self.parts)

    def close(self):
        if self._handle is None:
            return
        try:
            self._handle.close()
        except OSError:
            pass
        self._handle = None
