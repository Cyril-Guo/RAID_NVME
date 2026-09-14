#!/usr/bin/env python3
"""CLI metrics: Total=selected cases; pass/fail from executed junit."""
from __future__ import annotations

import glob
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path


def empty_stats():
    return {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}


def selected_slot_count(path: str = "test_items.txt") -> int:
    try:
        from nvme_raid_test import _parse_selection

        return len(_parse_selection(Path(path)))
    except Exception:
        pass
    text = Path(path).read_text(encoding="utf-8", errors="replace") if Path(path).is_file() else ""
    match = re.search(
        r"# === BEGIN SELECTION.*?===\n(.*?)# === END SELECTION",
        text,
        flags=re.S,
    )
    body = match.group(1) if match else text
    count = 0
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.split()[0].startswith("test_cli_"):
            count += 1
    return count


def count_suite_cases(suite):
    stats = empty_stats()
    for case in suite.findall("testcase"):
        stats["tests"] += 1
        if case.find("failure") is not None:
            stats["failures"] += 1
        if case.find("error") is not None:
            stats["errors"] += 1
        if case.find("skipped") is not None:
            stats["skipped"] += 1
    return stats


def add_stats(total, item):
    for key in total:
        total[key] += item.get(key, 0)


def junit_metrics(paths=None):
    stats = empty_stats()
    candidates = paths or sorted(
        glob.glob("node-report_*.xml") + glob.glob("report_*.xml")
    )
    for path in candidates:
        try:
            root = ET.parse(path).getroot()
        except (ET.ParseError, OSError):
            continue
        if root.tag == "testsuite":
            add_stats(stats, count_suite_cases(root))
            continue
        for suite in root.findall(".//testsuite"):
            add_stats(stats, count_suite_cases(suite))
    return stats


def main() -> int:
    selected = selected_slot_count()
    executed = junit_metrics()
    passed = max(
        0,
        executed["tests"]
        - executed["failures"]
        - executed["errors"]
        - executed["skipped"],
    )
    failed = executed["failures"]
    errors = executed["errors"]
    if selected > 0:
        skipped = max(0, selected - passed - failed - errors)
        total = selected
    else:
        total = executed["tests"]
        skipped = executed["skipped"]
    out = {
        "total": total,
        "failed": failed,
        "errors": errors,
        "skipped": skipped,
        "selected": selected,
        "executed": executed["tests"],
    }
    Path("report_metrics.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(out, ensure_ascii=False))
    for key, value in out.items():
        print(f"{key.upper()}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
