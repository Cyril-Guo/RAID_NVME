"""Merge test records from JUnit and native Allure without losing either source."""
import glob
import json
import os
import xml.etree.ElementTree as ET

try:
    from ci.report_identity import case_run_key, function_name, host, run_key
except ModuleNotFoundError:
    from report_identity import case_run_key, function_name, host, run_key


STATUS_RANK = {"passed": 0, "skipped": 1, "failed": 2, "broken": 3}


def case_status(case):
    if case.find("error") is not None:
        return "broken"
    if case.find("failure") is not None:
        return "failed"
    if case.find("skipped") is not None:
        return "skipped"
    return "passed"


def store_worst(records, identity, status):
    if status not in STATUS_RANK:
        status = "passed"
    if STATUS_RANK[status] > STATUS_RANK.get(records.get(identity, ""), -1):
        records[identity] = status


def merged_test_metrics(is_node_junit_report, is_infra_result):
    """Return status counts merged by host, run key and test function."""
    records = {}
    for path in glob.glob("report_*.xml"):
        if not is_node_junit_report(path):
            continue
        try:
            root = ET.parse(path).getroot()
        except (ET.ParseError, OSError):
            continue
        node = os.path.basename(path).removeprefix("report_").removesuffix(".xml")
        node = node.removesuffix("_physical")
        for index, case in enumerate(root.iter("testcase")):
            function = str(case.get("name") or "")
            identity = (node, case_run_key(case), function)
            if not function:
                identity = ("junit", path, str(index))
            store_worst(records, identity, case_status(case))

    for path in glob.glob("allure-results/*-result.json"):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                result = json.load(handle)
        except (OSError, json.JSONDecodeError):
            continue
        if is_infra_result(result):
            continue
        function = function_name(result)
        identity = (host(result), run_key(result), function)
        if not function:
            identity = ("allure", path, str(result.get("name") or ""))
        store_worst(records, identity, str(result.get("status") or "passed"))

    stats = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    for status in records.values():
        stats["tests"] += 1
        if status == "failed":
            stats["failures"] += 1
        elif status == "broken":
            stats["errors"] += 1
        elif status == "skipped":
            stats["skipped"] += 1
    return stats
