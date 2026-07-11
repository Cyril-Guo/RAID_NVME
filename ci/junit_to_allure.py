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


def write_result(allure_dir, suite_name, case):
    test_uuid = str(uuid.uuid4())
    status, detail = status_from_case(case)
    name = case.attrib.get("name", "unknown")
    classname = case.attrib.get("classname", suite_name or "unknown")
    result = {
        "uuid": test_uuid,
        "historyId": f"{classname}::{name}",
        "testCaseId": f"{classname}::{name}",
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


def main():
    allure_dir = "allure-results"
    ensure_dir(allure_dir)

    existing = glob.glob(os.path.join(allure_dir, "*-result.json"))
    if existing:
        print(f"allure result files already exist: {len(existing)}")
        return 0

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
                write_result(allure_dir, suite_name, case)
                generated += 1

    print(f"generated allure result files from junit: {generated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
