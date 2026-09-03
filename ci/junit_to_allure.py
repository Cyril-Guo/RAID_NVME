import glob
import json
import os
import re
import time
import uuid
import xml.etree.ElementTree as ET

try:
    from ci.extract_failure_summary import extract_failure_lines
    from ci.report_metrics import is_node_junit_report
    from ci.execution_failure import execution_context, reconcile_execution_failures
    from ci.allure_sections import organize_results, native_case_exists
    from ci.allure_infra import write_environment_prepare_results, write_physical_restore_results, write_failed_execution_results
except ModuleNotFoundError:
    from extract_failure_summary import extract_failure_lines
    from report_metrics import is_node_junit_report
    from execution_failure import execution_context, reconcile_execution_failures
    from allure_sections import organize_results, native_case_exists
    from allure_infra import write_environment_prepare_results, write_physical_restore_results, write_failed_execution_results


def normalize_root(root):
    if root.tag == "testsuite":
        suites = [root]
    else:
        suites = root.findall(".//testsuite")
    return suites


def status_from_case(case):
    failure = case.find("failure")
    error = case.find("error")
    skipped = case.find("skipped")
    if failure is not None:
        return "failed", failure
    if error is not None:
        return "broken", error
    if skipped is not None:
        return "skipped", skipped
    return "passed", None


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def report_context(junit_file):
    base = os.path.basename(junit_file)
    stem = base.removeprefix("report_").removesuffix(".xml")
    if stem.endswith("_physical"):
        node = stem.removesuffix("_physical")
        if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", node):
            return node, "physical"
        return "", ""
    if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", stem):
        return execution_context(f"test_execution_{stem}.log")
    return "", ""


def context_label(target_kind):
    if target_kind == "physical":
        return "Physical"
    if target_kind == "qemu":
        return "QEMU"
    return target_kind or "unknown"


def result_key(classname, name, target_node="", target_kind=""):
    context = "::".join(part for part in (target_node, target_kind) if part)
    if context:
        return f"{context}::{classname}::{name}"
    return f"{classname}::{name}"


def existing_history_ids(allure_dir):
    ids = set()
    for path in glob.glob(os.path.join(allure_dir, "*-result.json")):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                result = json.load(handle)
        except (OSError, json.JSONDecodeError):
            continue
        history_id = result.get("historyId")
        if history_id:
            ids.add(history_id)
    return ids


def result_matches_item(result, item):
    text = " ".join(
        str(result.get(key, "")).lower()
        for key in ("name", "fullName", "historyId", "testCaseId")
    )
    labels = {x.get("name"): x.get("value") for x in result.get("labels", [])}
    if labels.get("run_key"):
        return labels["run_key"] == item
    aliases = {
        "lawdisk": ("lawdisk", "lawdiskstress"),
        "filesystem": ("filesystem", "filesystemstress"),
        "mix": ("mix", "mix_stress"),
        "reboot": ("reboot", "reboot_powercycle"),
        "dc": ("dc", "dc_powercycle"),
        "basic_io": ("basic_io", "test_basic_io"),
        "basic_rebuild_io": ("basic_rebuild_io", "test_basic_rebuild_io"),
    }
    return any(alias in text for alias in aliases.get(item, (item,)))


def attach_pending_monitor_logs(allure_dir):
    return sum(_attach_monitor_sidecar(allure_dir, path) for path in
               glob.glob(os.path.join(allure_dir, "*monitor_attachments.json")))


def _attach_monitor_sidecar(allure_dir, sidecar):
    try:
        with open(sidecar, "r", encoding="utf-8") as handle:
            pending = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return 0

    attached = 0
    for path in glob.glob(os.path.join(allure_dir, "*-result.json")):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                result = json.load(handle)
        except (OSError, json.JSONDecodeError):
            continue

        changed = False
        for entry in pending:
            entry_host = entry.get("host")
            entry_target = entry.get("target")
            labels = {label.get("name"): label.get("value") for label in result.get("labels", [])}
            if entry_host and labels.get("host") != entry_host:
                continue
            if entry_target and labels.get("target") != entry_target:
                continue
            if entry.get("scope") != "node" and not result_matches_item(result, entry.get("item", "")):
                continue
            attachment = entry.get("attachment")
            if not attachment:
                continue
            attachments = result.setdefault("attachments", [])
            if not any(existing.get("source") == attachment.get("source") for existing in attachments):
                attachments.append(attachment)
                attached += 1
                changed = True

        if changed:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(result, handle, ensure_ascii=False)

    return attached


def write_result(allure_dir, suite_name, case, target_node="", target_kind=""):
    test_uuid = str(uuid.uuid4())
    status, detail = status_from_case(case)
    name = case.attrib.get("name", "unknown")
    classname = case.attrib.get("classname", suite_name or "unknown")
    key = result_key(classname, name, target_node, target_kind)
    label = context_label(target_kind)
    display_name = f"[{label} {target_node}] {name}" if target_node else name
    properties = {p.get("name"): p.get("value") for p in case.findall("properties/property")}
    duration_ms = int(float(case.get("time", "0")) * 1000)
    start_ms = int(properties.get("started_at_ms", "0")) or int(time.time() * 1000) - duration_ms
    result = {
        "uuid": test_uuid,
        "historyId": key,
        "testCaseId": key,
        "fullName": f"{target_kind}:{target_node}:{classname}#{name}" if target_node else f"{classname}#{name}",
        "name": display_name,
        "status": status,
        "stage": "finished",
        "start": start_ms,
        "stop": start_ms + duration_ms,
        "labels": [
            {"name": "suite", "value": suite_name or "unknown"},
            {"name": "parentSuite", "value": "测试日志"},
            {"name": "package", "value": classname},
            {"name": "testClass", "value": classname},
            {"name": "host", "value": target_node or "jenkins"},
            {"name": "target", "value": target_kind or "unknown"},
            {"name": "framework", "value": "pytest"},
            {"name": "language", "value": "python"},
        ],
    }

    for prop in case.findall("properties/property"):
        if prop.get("name") == "run_key":
            result["labels"].append({"name": "run_key", "value": prop.get("value")})

    if detail is not None:
        message = detail.attrib.get("message", "") or (detail.text or "").strip()
        trace = (detail.text or "").strip()
        result["statusDetails"] = {
            "message": message or status,
            "trace": trace or message or status,
        }

    with open(os.path.join(allure_dir, f"{test_uuid}-result.json"), "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False)


def main():
    allure_dir = "allure-results"
    ensure_dir(allure_dir)

    recovered = reconcile_execution_failures()
    existing_ids = existing_history_ids(allure_dir)
    junit_files = sorted(
        path for path in glob.glob("report_*.xml") if is_node_junit_report(path)
    )
    generated = 0
    for junit_file in junit_files:
        try:
            root = ET.parse(junit_file).getroot()
        except ET.ParseError:
            continue
        target_node, target_kind = report_context(junit_file)

        for suite in normalize_root(root):
            suite_name = suite.attrib.get("name", "unknown")
            for case in suite.findall("testcase"):
                name = case.attrib.get("name", "unknown")
                classname = case.attrib.get("classname", suite_name or "unknown")
                key = result_key(classname, name, target_node, target_kind)
                if key in existing_ids or native_case_exists(allure_dir, case, target_node, target_kind):
                    continue
                write_result(allure_dir, suite_name, case, target_node, target_kind)
                existing_ids.add(key)
                generated += 1

    env_generated = write_environment_prepare_results(allure_dir, existing_ids)
    restore_generated = write_physical_restore_results(allure_dir, existing_ids)
    execution_generated = write_failed_execution_results(allure_dir, existing_ids)
    attached = attach_pending_monitor_logs(allure_dir)
    console_attached = organize_results(allure_dir)
    print(
        f"generated allure result files from junit: {generated}, recovered cases: {recovered}, "
        f"environment prepare results: {env_generated}, "
        f"physical restore results: {restore_generated}, "
        f"failed execution results: {execution_generated}, attached monitor logs: {attached}, "
        f"attached Jenkins console to results: {console_attached}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
