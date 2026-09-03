import glob
import json
import os
import re
import xml.etree.ElementTree as ET

try:
    from ci.execution_failure import unreported_failures, execution_context
except ModuleNotFoundError:
    from execution_failure import unreported_failures, execution_context


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


def _read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return ""


def status_log_infra_metrics(seen=None):
    """Count each failed env/execution/restore log as one execution item."""
    stats = empty_stats()
    seen = seen or set()

    for path in sorted(glob.glob("environment_prepare_*.log")):
        text = _read_text(path)
        node = os.path.basename(path).removeprefix("environment_prepare_").removesuffix(".log")
        if "ENVIRONMENT_PREPARE_STATUS=failed" in text and f"Environment_Prepare_{node}" not in seen:
            stats["tests"] += 1
            stats["errors"] += 1
        if "PHYSICAL_RESTORE_STATUS=failed" in text and f"Physical_Restore_{node}" not in seen:
            stats["tests"] += 1
            stats["errors"] += 1

    for path, _context in unreported_failures():
        node, kind = execution_context(path)
        label = "Physical" if kind == "physical" else "QEMU"
        if f"Test_Execution_{label}_{node}" in seen:
            continue
        stats["tests"] += 1
        stats["errors"] += 1

    return stats


def infra_metrics():
    """Prefer Allure infra results; fall back to status logs so each node/step counts."""
    infra_allure = allure_metrics(infra_only=True)
    seen = set()
    for path in glob.glob("allure-results/*-result.json"):
        try:
            result = json.loads(_read_text(path))
        except ValueError:
            continue
        if is_infra_result(result):
            seen.add(result.get("name", ""))
    add_stats(infra_allure, status_log_infra_metrics(seen))
    return infra_allure


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


def failed_case_names(limit=6):
    names = []
    for path in sorted(glob.glob("report_*.xml")):
        if not is_node_junit_report(path):
            continue
        try:
            root = ET.parse(path).getroot()
        except (ET.ParseError, OSError):
            continue
        node = os.path.basename(path).removeprefix("report_").removesuffix(".xml")
        for case in root.iter("testcase"):
            if case.find("failure") is not None or case.find("error") is not None:
                names.append(f"{node}: {case.get('name', 'unknown')}")
    if not names:
        for path in sorted(glob.glob("allure-results/*-result.json")):
            try:
                result = json.loads(_read_text(path))
            except ValueError:
                continue
            if result.get("status") in ("failed", "broken"):
                names.append(result.get("name", "unknown"))
    names = list(dict.fromkeys(names))
    return names[:limit] + ([f"... {len(names) - limit} more; see report"] if len(names) > limit else [])


if __name__ == "__main__":
    raise SystemExit(main())
