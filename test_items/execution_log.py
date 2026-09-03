"""Durable case output with a best-effort console mirror."""
import errno
import os
from pathlib import Path


def emit(text, end="\n"):
    case_root = os.environ.get("RAID_NVME_CASE_ROOT")
    if case_root:
        try:
            with (Path(case_root) / "case_command.log").open("a", encoding="utf-8") as handle:
                handle.write(text + end)
        except OSError as exc:
            # A full/unavailable filesystem must not mask the original test error.
            try:
                print(f"[LOG_WARNING] Cannot persist case output: {exc}", flush=True)
            except OSError:
                pass
    try:
        print(text, end=end, flush=True)
    except OSError as exc:
        if not isinstance(exc, BrokenPipeError) and exc.errno != errno.EPIPE:
            raise
