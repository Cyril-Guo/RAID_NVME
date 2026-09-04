"""Merge JUnit and native Allure test records without hiding either source."""
import glob
import json
import os
import re
import xml.etree.ElementTree as ET


STATUS_RANK = {"passed": 0, "skipped": 1, "failed": 2, "broken": 3}
DISPLAY_PREFIX_RE = re.compile(r"^\[(?:QEMU|Physical)\s+[^\]]+\]\s*")


def labels(result):
    return {
        str(label.get("name") or ""): str(label.get("value") or "")
        for label in result.get("labels") or []
    }


def junit_context(path):
    stem = os.path.basename(path).removeprefix("report_").removesuffix(".xml")
    if stem.endswith("_physical"):
        return stem.removesuffix("_physical"), "physical"
    execution_log = f"test_execution_{stem}.log"
    try:
        with open(execution_log, "r", encoding="utf-8", errors="replace") as handle:
            match = re.search(r"^TEST_EXECUTION_TARGET=(qemu|physical)$", handle.read(), re.MULTILINE)
    except OSError:
        match = None
    return stem, match.group(1) if match else "unknown"


def case_status(case):
    if case.find("error") is not None:
        return "broken"
    if case.find("failure") is not None:
        return "failed"
    if case.find("skipped") is not None:
        return "skipped"
    return "passed"


def allure_function_name(result):
    full_name = str(result.get("fullName") or "")
    if "#" in full_name:
        return full_name.rsplit("#", 1)[1]
    name = DISPLAY_PREFIX_RE.sub("", str(result.get("name") or ""))
    return name


def store_worst(records, identity, status):
    status = status if status in STATUS_RANK else "passed"
    if STATUS_RANK[status] > STATUS_RANK.get(records.get(identity, ""), -1):
        records[identity] = status


def merged_test_metrics(is_node_junit_report, is_infra_result):
    records = {}
    for path in glob.glob("report_*.xml"):
        if not is_node_junit_report(path):
            continue
        try:
            root = ET.parse(path).getroot()
        except (ET.ParseError, OSError):
            continue
        host, target = junit_context(path)
        for index, case in enumerate(root.iter("testcase")):
            name = str(case.get("name") or "")
            identity = (host, target, name)
            if not name:
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
        meta = labels(result)
        name = allure_function_name(result)
        identity = (meta.get("host", "unknown"), meta.get("target", "unknown"), name)
        if not name:
            identity = ("allure", path, str(result.get("uuid") or ""))
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
