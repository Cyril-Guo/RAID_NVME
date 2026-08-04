import glob
import json
import os
import re
import xml.etree.ElementTree as ET


STAT_KEYS = ("tests", "failures", "errors", "skipped")
INFRA_SUITES = frozenset({"Environment_Prepare", "Test_Execution", "Physical_Restore"})
NODE_REPORT_RE = re.compile(r"^report_.+\..+\.xml$|^report_.+_physical\.xml$")


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


def is_node_junit_report(path):
    """Accept node-level reports only; skip per-item report_<case>.xml files."""
    name = os.path.basename(path)
    return bool(NODE_REPORT_RE.match(name))


def junit_metrics(paths=None):
    stats = empty_stats()
    candidates = paths or glob.glob("report_*.xml")
    for path in candidates:
        if paths is None and not is_node_junit_report(path):
            continue
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


def result_suite(result):
    for label in result.get("labels") or []:
        if label.get("name") == "suite":
            return str(label.get("value") or "")
    return ""


def is_infra_result(result):
    suite = result_suite(result)
    if suite in INFRA_SUITES:
        return True
    name = str(result.get("name") or "")
    return (
        name.startswith("Environment_Prepare_")
        or name.startswith("Test_Execution_")
        or name.startswith("Physical_Restore_")
    )


def allure_metrics(paths=None, infra_only=False):
    stats = empty_stats()
    for path in paths or glob.glob("allure-results/*-result.json"):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                result = json.load(handle)
        except (OSError, json.JSONDecodeError):
            continue

        if infra_only and not is_infra_result(result):
            continue
        if not infra_only and is_infra_result(result):
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
    junit_stats = junit_metrics()
    infra_allure = allure_metrics(infra_only=True)
    test_allure = allure_metrics(infra_only=False)

    if junit_stats["tests"] > 0:
        stats = dict(junit_stats)
        add_stats(stats, infra_allure)
        return {**stats, "kind": "tests"}

    if test_allure["tests"] > 0:
        stats = dict(test_allure)
        add_stats(stats, infra_allure)
        return {**stats, "kind": "tests"}

    if infra_allure["tests"] > 0:
        return {**infra_allure, "kind": "infra"}

    return {**empty_stats(), "kind": "empty"}


def main():
    stats = report_metrics()
    print(
        f"{stats['tests']} {stats['failures']} {stats['errors']} {stats['skipped']} {stats['kind']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
