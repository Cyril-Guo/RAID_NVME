import glob
import json
import os
import uuid
import xml.etree.ElementTree as ET


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


def result_key(classname, name):
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
    aliases = {
        "lawdisk": ("lawdisk", "lawdiskstress"),
        "filesystem": ("filesystem", "filesystemstress"),
        "mix": ("mix", "mix_stress"),
        "reboot": ("reboot", "reboot_powercycle"),
        "dc": ("dc", "dc_powercycle"),
    }
    return any(alias in text for alias in aliases.get(item, (item,)))


def attach_pending_monitor_logs(allure_dir):
    sidecar = os.path.join(allure_dir, "monitor_attachments.json")
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
            if not result_matches_item(result, entry.get("item", "")):
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


def write_result(allure_dir, suite_name, case):
    test_uuid = str(uuid.uuid4())
    status, detail = status_from_case(case)
    name = case.attrib.get("name", "unknown")
    classname = case.attrib.get("classname", suite_name or "unknown")
    result = {
        "uuid": test_uuid,
        "historyId": result_key(classname, name),
        "testCaseId": result_key(classname, name),
        "fullName": f"{classname}#{name}",
        "name": name,
        "status": status,
        "stage": "finished",
        "labels": [
            {"name": "suite", "value": suite_name or "unknown"},
            {"name": "package", "value": classname},
            {"name": "testClass", "value": classname},
            {"name": "host", "value": "jenkins"},
            {"name": "framework", "value": "pytest"},
            {"name": "language", "value": "python"},
        ],
    }

    if detail is not None:
        message = detail.attrib.get("message", "") or (detail.text or "").strip()
        trace = (detail.text or "").strip()
        result["statusDetails"] = {
            "message": message or status,
            "trace": trace or message or status,
        }

    with open(os.path.join(allure_dir, f"{test_uuid}-result.json"), "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False)


def write_environment_prepare_results(allure_dir):
    generated = 0
    for path in glob.glob("environment_prepare_*.log"):
        log_name = os.path.basename(path)
        node = log_name.removeprefix("environment_prepare_").removesuffix(".log")
        source = f"{uuid.uuid4()}-environment-prepare.log"
        target = os.path.join(allure_dir, source)
        with open(path, "rb") as src, open(target, "wb") as dst:
            dst.write(src.read())

        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                text = handle.read()
        except OSError:
            text = ""

        status = "broken" if "ENVIRONMENT_PREPARE_STATUS=failed" in text else "passed"
        test_uuid = str(uuid.uuid4())
        result = {
            "uuid": test_uuid,
            "historyId": f"Environment_Prepare::{node}",
            "testCaseId": f"Environment_Prepare::{node}",
            "fullName": f"Environment_Prepare#{node}",
            "name": f"Environment_Prepare_{node}",
            "status": status,
            "stage": "finished",
            "labels": [
                {"name": "suite", "value": "Environment_Prepare"},
                {"name": "package", "value": "Environment_Prepare"},
                {"name": "testClass", "value": "Environment_Prepare"},
                {"name": "host", "value": node},
                {"name": "framework", "value": "jenkins"},
                {"name": "language", "value": "shell"},
            ],
            "attachments": [
                {
                    "name": f"Environment_Prepare_{node}",
                    "source": source,
                    "type": "text/plain",
                }
            ],
        }
        if status != "passed":
            result["statusDetails"] = {
                "message": "Environment prepare failed",
                "trace": "\n".join(text.splitlines()[-120:]),
            }

        with open(os.path.join(allure_dir, f"{test_uuid}-result.json"), "w", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False)
        generated += 1
    return generated


def main():
    allure_dir = "allure-results"
    ensure_dir(allure_dir)

    existing_ids = existing_history_ids(allure_dir)
    junit_files = glob.glob("report_*.xml")
    generated = 0
    for junit_file in junit_files:
        try:
            root = ET.parse(junit_file).getroot()
        except ET.ParseError:
            continue

        for suite in normalize_root(root):
            suite_name = suite.attrib.get("name", "unknown")
            for case in suite.findall("testcase"):
                name = case.attrib.get("name", "unknown")
                classname = case.attrib.get("classname", suite_name or "unknown")
                if result_key(classname, name) in existing_ids:
                    continue
                write_result(allure_dir, suite_name, case)
                existing_ids.add(result_key(classname, name))
                generated += 1

    env_generated = write_environment_prepare_results(allure_dir)
    attached = attach_pending_monitor_logs(allure_dir)
    print(
        f"generated allure result files from junit: {generated}, "
        f"environment prepare results: {env_generated}, attached monitor logs: {attached}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
