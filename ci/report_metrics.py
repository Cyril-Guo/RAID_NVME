import glob
import json
import os
import re
import xml.etree.ElementTree as ET

try:
    from ci.build_status import console_was_manually_aborted
except ModuleNotFoundError:
    from build_status import console_was_manually_aborted


STAT_KEYS = ("tests", "failures", "errors", "skipped")
INFRA_SUITES = frozenset({"Environment_Prepare", "Test_Execution", "Physical_Restore"})
NODE_REPORT_RE = re.compile(r"^report_.+\..+\.xml$")
EXECUTION_HARD_MARKERS = (
    "FIO stage failed",
    "FIO stage abort",
    "MIX_FAIL_ON_ANY=yes, fail",
    "idle watchdog timeout",
    "idle watchdog fired",
)


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


def _read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return ""


def execution_log_has_explicit_failure(text):
    return "TEST_EXECUTION_STATUS=failed" in (text or "") or any(
        marker in (text or "") for marker in EXECUTION_HARD_MARKERS
    )


def execution_log_needs_result(text):
    """Treat explicit failures and abort/incomplete logs (no passed marker) as reportable.

    Also surface hard FIO stops even when the remote wrapper wrongly wrote
    TEST_EXECUTION_STATUS=passed (pytest stayed green after Fio_All swallowed rc).
    """
    if execution_log_has_explicit_failure(text):
        return True
    if "TEST_EXECUTION_STATUS=passed" in text:
        return False
    if "TEST_EXECUTION_STATUS=failed" in text:
        return True
    lowered = (text or "").lower()
    return (not (text or "").strip()) or ("aborted" in lowered) or ("idle watchdog fired" in lowered)


def report_has_testcases(target_node):
    path = f"report_{target_node}.xml"
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return False
    return root.find(".//testcase") is not None or root.tag == "testcase"


def report_has_failures_or_errors(target_node):
    path = f"report_{target_node}.xml"
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return False
    return root.find(".//failure") is not None or root.find(".//error") is not None


def status_log_infra_metrics():
    """Count each failed env/execution/restore log as one execution item."""
    stats = empty_stats()
    manually_aborted = console_was_manually_aborted()

    for path in sorted(glob.glob("environment_prepare_*.log")):
        text = _read_text(path)
        if "ENVIRONMENT_PREPARE_STATUS=failed" in text:
            stats["tests"] += 1
            stats["errors"] += 1
        if "PHYSICAL_RESTORE_STATUS=failed" in text:
            stats["tests"] += 1
            stats["errors"] += 1

    for path in sorted(glob.glob("test_execution_*.log")):
        text = _read_text(path)
        if manually_aborted and not execution_log_has_explicit_failure(text):
            continue
        if not execution_log_needs_result(text):
            continue
        stem = os.path.basename(path).removeprefix("test_execution_").removesuffix(".log")
        target_node = stem.removesuffix("_physical")
        # If JUnit already captured a testcase failure/error, do not double-count the node-level
        # execution failure. But if JUnit only shows passed cases while execution log failed,
        # surface one infra error so Feishu/Allure cannot misreport the build as green.
        if report_has_testcases(target_node) and report_has_failures_or_errors(target_node):
            continue
        stats["tests"] += 1
        stats["errors"] += 1

    return stats


def infra_metrics():
    """Prefer Allure infra results; fall back to status logs so each node/step counts."""
    infra_allure = allure_metrics(infra_only=True)
    if infra_allure["tests"] > 0:
        return infra_allure
    return status_log_infra_metrics()


def report_metrics():
    junit_stats = junit_metrics()
    infra_stats = infra_metrics()
    test_allure = allure_metrics(infra_only=False)

    if junit_stats["tests"] > 0:
        stats = dict(junit_stats)
        add_stats(stats, infra_stats)
        return {**stats, "kind": "tests"}

    if test_allure["tests"] > 0:
        stats = dict(test_allure)
        add_stats(stats, infra_stats)
        return {**stats, "kind": "tests"}

    if infra_stats["tests"] > 0:
        return {**infra_stats, "kind": "infra"}

    return {**empty_stats(), "kind": "empty"}


def main():
    stats = report_metrics()
    print(
        f"{stats['tests']} {stats['failures']} {stats['errors']} {stats['skipped']} {stats['kind']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
