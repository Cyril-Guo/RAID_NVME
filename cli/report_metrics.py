#!/usr/bin/env python3
"""Parse node-report_*.xml into simple counters for Feishu."""
from __future__ import annotations

import glob
import json
import os
import xml.etree.ElementTree as ET


def empty_stats():
    return {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}


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
    candidates = paths or sorted(glob.glob("node-report_*.xml"))
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
    metrics = junit_metrics()
    out = {
        "total": metrics["tests"],
        "failed": metrics["failures"],
        "errors": metrics["errors"],
        "skipped": metrics["skipped"],
    }
    with open("report_metrics.json", "w", encoding="utf-8") as handle:
        json.dump(out, handle, ensure_ascii=False, indent=2)
    print(json.dumps(out, ensure_ascii=False))
    # also export shell-friendly lines
    for key, value in out.items():
        print(f"{key.upper()}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
