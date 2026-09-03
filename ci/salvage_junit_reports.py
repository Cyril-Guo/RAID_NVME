#!/usr/bin/env python3
"""Merge per-item JUnit reports and optionally stop leftover stress monitors.

Intended to run on the test target after nvme_raid_test.py exits or is killed.
The pkill pattern deliberately avoids matching this process command line.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

# Allow `python3 ci/salvage_junit_reports.py` when cwd is the repo root but
# the script directory itself is not on sys.path.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import nvme_raid_test
from ci.salvage_case_artifacts import recover_case_artifacts

# Bracket trick so `pkill -f` does not match the shell/python cmdline that embeds this text.
MONITOR_PKILL_PATTERN = "[S]tress_Monitor/main.py"


def monitor_running():
    result = subprocess.run(
        ["pgrep", "-f", MONITOR_PKILL_PATTERN],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def stop_monitor(wait_seconds=10):
    subprocess.run(
        ["pkill", "-TERM", "-f", MONITOR_PKILL_PATTERN],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    for _ in range(wait_seconds):
        if not monitor_running():
            return
        time.sleep(1)
    subprocess.run(
        ["pkill", "-KILL", "-f", MONITOR_PKILL_PATTERN],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def item_reports(directory):
    root = Path(directory)
    return [item for item in nvme_raid_test.TEST_ITEMS if (root / f"report_{item}.xml").exists()]


def merge_from_directory(directory, output):
    directory = str(Path(directory).resolve())
    output_path = Path(output)
    if not output_path.is_absolute():
        output_path = Path(directory) / output_path
    items = item_reports(directory)
    if not items:
        print("no per-item junit reports found to merge")
        return []

    cwd = os.getcwd()
    try:
        os.chdir(directory)
        nvme_raid_test.merge_junit_reports(items, str(output_path))
    finally:
        os.chdir(cwd)
    print("merged junit items:", ",".join(items))
    return items


def main(argv=None):
    parser = argparse.ArgumentParser(description="Salvage/merge per-item JUnit reports.")
    parser.add_argument("--from-dir", default=".", help="Directory containing report_<item>.xml files")
    parser.add_argument("--output", default=nvme_raid_test.JUNIT_FINAL)
    parser.add_argument("--stop-monitor", action="store_true")
    args = parser.parse_args(argv)

    if args.stop_monitor:
        stop_monitor()

    recover_case_artifacts(args.from_dir, nvme_raid_test.TEST_ITEMS)
    merge_from_directory(args.from_dir, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
