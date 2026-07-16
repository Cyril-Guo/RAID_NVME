import glob
import json
import xml.etree.ElementTree as ET


STAT_KEYS = ("tests", "failures", "errors", "skipped")


def empty_stats():
    return {key: 0 for key in STAT_KEYS}


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
    for key in STAT_KEYS:
        total[key] += item.get(key, 0)


def junit_metrics(paths=None):
    stats = empty_stats()
    for path in paths or glob.glob("report_*.xml"):
        try:
            root = ET.parse(path).getroot()
        except (ET.ParseError, OSError):
            continue

        if root.tag == "testsuite":
            add_stats(stats, count_suite_cases(root))
            continue

        suites = root.findall(".//testsuite")
        if suites:
            for suite in suites:
                add_stats(stats, count_suite_cases(suite))
            continue

        for case in root.findall(".//testcase"):
            stats["tests"] += 1
            if case.find("failure") is not None:
                stats["failures"] += 1
            if case.find("error") is not None:
                stats["errors"] += 1
            if case.find("skipped") is not None:
                stats["skipped"] += 1

    return stats


def allure_metrics(paths=None):
    stats = empty_stats()
    for path in paths or glob.glob("allure-results/*-result.json"):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                result = json.load(handle)
        except (OSError, json.JSONDecodeError):
            continue

        status = result.get("status")
        stats["tests"] += 1
        if status == "failed":
            stats["failures"] += 1
        elif status == "broken":
            stats["errors"] += 1
        elif status == "skipped":
            stats["skipped"] += 1

    return stats


def report_metrics():
    stats = junit_metrics()
    if stats["tests"] == 0:
        stats = allure_metrics()
    return stats


def main():
    stats = report_metrics()
    print(f"{stats['tests']} {stats['failures']} {stats['errors']} {stats['skipped']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
