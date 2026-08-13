"""Resolve paths inside the active per-case workspace.

nvme_raid_test.py runs each item under cases/<item>/ and symlinks test_items/.
Using dirname(__file__) follows that symlink back to the shared build tree, so
IO_Stress logs would land in build-N/IO_Stress instead of cases/<item>/IO_Stress.
Prefer RAID_NVME_CASE_ROOT / cwd instead.
"""
from __future__ import annotations

import os


def case_root() -> str:
    env = os.environ.get("RAID_NVME_CASE_ROOT", "").strip()
    if env and os.path.isdir(env):
        return os.path.abspath(env)
    cwd = os.getcwd()
    if os.path.isdir(os.path.join(cwd, "IO_Stress")):
        return os.path.abspath(cwd)
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def io_stress_dir() -> str:
    return os.path.join(case_root(), "IO_Stress")


def stress_monitor_dir() -> str:
    return os.path.join(case_root(), "Stress_Monitor")
