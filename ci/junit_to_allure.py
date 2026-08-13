import glob
import json
import os
import re
import uuid
import xml.etree.ElementTree as ET

try:
    from ci.extract_failure_summary import extract_failure_lines
    from ci.report_metrics import is_node_junit_report
except ModuleNotFoundError:
    from extract_failure_summary import extract_failure_lines
    from report_metrics import is_node_junit_report


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
    stem = base.removeprefix("report_").removesuffix(".xml").removesuffix("_physical")
    if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", stem):
        return stem, "physical"
    return "", ""


def context_label(target_kind):
    return "Physical" if target_kind else "unknown"


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
            entry_host = entry.get("host")
            entry_target = entry.get("target")
            labels = {label.get("name"): label.get("value") for label in result.get("labels", [])}
            if entry_host and labels.get("host") != entry_host:
                continue
            if entry_target and labels.get("target") != entry_target:
                continue
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


FIO_FAILURE_LINE_RE = re.compile(
    r"FIO (?:command failed|stage failed|stage abort).*model=.*elapsed=",
    re.IGNORECASE,
)


def extract_fio_failure_details(text):
    """Return structured FIO failure lines that include model + elapsed."""
    lines = []
    seen = set()
    for raw in (text or "").splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if not line or not FIO_FAILURE_LINE_RE.search(line):
            continue
        key = line.lower()
        if key in seen:
            continue
        seen.add(key)
        lines.append(line)
    return lines


def write_result(allure_dir, suite_name, case, target_node="", target_kind=""):
    test_uuid = str(uuid.uuid4())
    status, detail = status_from_case(case)
    name = case.attrib.get("name", "unknown")
    classname = case.attrib.get("classname", suite_name or "unknown")
    key = result_key(classname, name, target_node, target_kind)
    label = context_label(target_kind)
    display_name = f"[{label} {target_node}] {name}" if target_node else name
    result = {
        "uuid": test_uuid,
        "historyId": key,
        "testCaseId": key,
        "fullName": f"{target_kind}:{target_node}:{classname}#{name}" if target_node else f"{classname}#{name}",
        "name": display_name,
        "status": status,
        "stage": "finished",
        "labels": [
            {"name": "suite", "value": suite_name or "unknown"},
            {"name": "package", "value": classname},
            {"name": "testClass", "value": classname},
            {"name": "host", "value": target_node or "jenkins"},
            {"name": "target", "value": target_kind or "unknown"},
            {"name": "framework", "value": "pytest"},
            {"name": "language", "value": "python"},
        ],
    }

    if detail is not None:
        message = detail.attrib.get("message", "") or (detail.text or "").strip()
        trace = (detail.text or "").strip()
        combined = "\n".join(part for part in (message, trace) if part)
        fio_details = extract_fio_failure_details(combined)
        if fio_details:
            # Surface model/elapsed as the Allure error title for "查看报告".
            result["statusDetails"] = {
                "message": fio_details[0],
                "trace": "\n".join(fio_details + ([trace] if trace else [])),
            }
            source = f"{uuid.uuid4()}-fio-failure-detail.txt"
            with open(os.path.join(allure_dir, source), "w", encoding="utf-8") as handle:
                handle.write("\n".join(fio_details) + "\n")
            result["attachments"] = [
                {
                    "name": "FIO Failure Detail (model/elapsed)",
                    "source": source,
                    "type": "text/plain",
                }
            ]
        else:
            result["statusDetails"] = {
                "message": message or status,
                "trace": trace or message or status,
            }

    with open(os.path.join(allure_dir, f"{test_uuid}-result.json"), "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False)


def write_status_log_results(
    allure_dir,
    existing_ids,
    *,
    status_token,
    suite_name,
    default_message,
    attachment_prefix,
):
    generated = 0
    for path in glob.glob("environment_prepare_*.log"):
        log_name = os.path.basename(path)
        node = log_name.removeprefix("environment_prepare_").removesuffix(".log")
        key = f"{suite_name}::{node}"
        if key in existing_ids:
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                text = handle.read()
        except OSError:
            text = ""

        if status_token not in text:
            continue

        source = f"{uuid.uuid4()}-{attachment_prefix}.log"
        target = os.path.join(allure_dir, source)
        with open(path, "rb") as src, open(target, "wb") as dst:
            dst.write(src.read())

        summary = extract_failure_lines(text)
        host = node.removesuffix("_physical")
        test_uuid = str(uuid.uuid4())
        result = {
            "uuid": test_uuid,
            "historyId": key,
            "testCaseId": key,
            "fullName": f"{suite_name}#{node}",
            "name": f"{suite_name}_{node}",
            "status": "broken",
            "stage": "finished",
            "labels": [
                {"name": "suite", "value": suite_name},
                {"name": "package", "value": suite_name},
                {"name": "testClass", "value": suite_name},
                {"name": "host", "value": host},
                {"name": "framework", "value": "jenkins"},
                {"name": "language", "value": "shell"},
            ],
            "attachments": [
                {
                    "name": f"{suite_name}_{node}",
                    "source": source,
                    "type": "text/plain",
                }
            ],
            "statusDetails": {
                "message": summary[0] if summary else default_message,
                "trace": "\n".join(summary or text.splitlines()[-120:]),
            },
        }

        with open(os.path.join(allure_dir, f"{test_uuid}-result.json"), "w", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False)
        existing_ids.add(key)
        generated += 1
    return generated


def write_environment_prepare_results(allure_dir, existing_ids):
    return write_status_log_results(
        allure_dir,
        existing_ids,
        status_token="ENVIRONMENT_PREPARE_STATUS=failed",
        suite_name="Environment_Prepare",
        default_message="Environment prepare failed",
        attachment_prefix="environment-prepare",
    )


def write_physical_restore_results(allure_dir, existing_ids):
    return write_status_log_results(
        allure_dir,
        existing_ids,
        status_token="PHYSICAL_RESTORE_STATUS=failed",
        suite_name="Physical_Restore",
        default_message="Physical host RAID restore failed",
        attachment_prefix="physical-restore",
    )


def execution_log_context(path):
    stem = os.path.basename(path).removeprefix("test_execution_").removesuffix(".log")
    target_node = stem.removesuffix("_physical")
    return target_node, "physical"


def report_has_testcases(target_node, target_kind):
    path = f"report_{target_node}.xml"
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return False
    return root.find(".//testcase") is not None or root.tag == "testcase"


def execution_log_needs_result(text):
    """Treat explicit failures and abort/incomplete logs (no passed marker) as reportable."""
    if "TEST_EXECUTION_STATUS=passed" in text:
        return False
    if "TEST_EXECUTION_STATUS=failed" in text:
        return True
    # Empty or truncated logs from ABORTED builds never write a terminal status.
    return True


def write_failed_execution_results(allure_dir, existing_ids):
    generated = 0
    for path in sorted(glob.glob("test_execution_*.log")):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                text = handle.read()
        except OSError:
            continue

        if not execution_log_needs_result(text):
            continue

        target_node, target_kind = execution_log_context(path)
        if report_has_testcases(target_node, target_kind):
            continue

        key = f"Test_Execution::{target_node}::{target_kind}"
        if key in existing_ids:
            continue

        source = f"{uuid.uuid4()}-test-execution.log"
        with open(path, "rb") as src, open(os.path.join(allure_dir, source), "wb") as dst:
            dst.write(src.read())

        summary = extract_failure_lines(text)
        fio_details = extract_fio_failure_details(text)
        if "TEST_EXECUTION_STATUS=failed" in text:
            default_message = "Remote test execution failed"
        else:
            default_message = "Remote test execution aborted or incomplete"
        if fio_details:
            default_message = fio_details[0]
            summary = fio_details + [line for line in summary if line not in fio_details]
        label = context_label(target_kind)
        test_uuid = str(uuid.uuid4())
        result = {
            "uuid": test_uuid,
            "historyId": key,
            "testCaseId": key,
            "fullName": f"Test_Execution#{target_node}#{target_kind}",
            "name": f"Test_Execution_{label}_{target_node}",
            "status": "broken",
            "stage": "finished",
            "labels": [
                {"name": "suite", "value": "Test_Execution"},
                {"name": "package", "value": "Test_Execution"},
                {"name": "testClass", "value": "Test_Execution"},
                {"name": "host", "value": target_node},
                {"name": "target", "value": target_kind},
                {"name": "framework", "value": "jenkins"},
                {"name": "language", "value": "shell"},
            ],
            "attachments": [
                {
                    "name": os.path.basename(path),
                    "source": source,
                    "type": "text/plain",
                }
            ],
            "statusDetails": {
                "message": summary[0] if summary else default_message,
                "trace": "\n".join(summary or text.splitlines()[-120:] or [default_message]),
            },
        }
        with open(os.path.join(allure_dir, f"{test_uuid}-result.json"), "w", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False)
        existing_ids.add(key)
        generated += 1
    return generated


def write_console_fallback_result(allure_dir, existing_ids, console_path="jenkins_console.log"):
    """Ensure ABORTED/infra builds still produce an Allure case when no other results exist."""
    if not os.path.isfile(console_path):
        return 0
    if glob.glob(os.path.join(allure_dir, "*-result.json")):
        return 0

    key = "Test_Execution::jenkins::console"
    if key in existing_ids:
        return 0

    try:
        with open(console_path, "r", encoding="utf-8", errors="replace") as handle:
            text = handle.read()
    except OSError:
        return 0

    source = f"{uuid.uuid4()}-jenkins-console.log"
    with open(console_path, "rb") as src, open(os.path.join(allure_dir, source), "wb") as dst:
        dst.write(src.read())

    summary = extract_failure_lines(text)
    if re.search(r"\bAborted by\b", text) or "Finished: ABORTED" in text:
        default_message = "Build aborted before countable test results were produced"
    else:
        default_message = "No countable test results were produced"
    test_uuid = str(uuid.uuid4())
    result = {
        "uuid": test_uuid,
        "historyId": key,
        "testCaseId": key,
        "fullName": "Test_Execution#jenkins#console",
        "name": "Test_Execution_Build_Console",
        "status": "broken",
        "stage": "finished",
        "labels": [
            {"name": "suite", "value": "Test_Execution"},
            {"name": "package", "value": "Test_Execution"},
            {"name": "testClass", "value": "Test_Execution"},
            {"name": "framework", "value": "jenkins"},
            {"name": "language", "value": "shell"},
        ],
        "attachments": [
            {
                "name": "Jenkins Console Output",
                "source": source,
                "type": "text/plain",
            }
        ],
        "statusDetails": {
            "message": summary[0] if summary else default_message,
            "trace": "\n".join(summary or text.splitlines()[-120:] or [default_message]),
        },
    }
    with open(os.path.join(allure_dir, f"{test_uuid}-result.json"), "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False)
    existing_ids.add(key)
    return 1


def attach_jenkins_console(allure_dir, console_path="jenkins_console.log"):
    if not os.path.isfile(console_path):
        return 0

    result_paths = sorted(glob.glob(os.path.join(allure_dir, "*-result.json")))
    if not result_paths:
        return 0

    source = f"{uuid.uuid4()}-jenkins-console.log"
    with open(console_path, "rb") as src, open(os.path.join(allure_dir, source), "wb") as dst:
        dst.write(src.read())

    attached = 0
    for path in result_paths:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                result = json.load(handle)
        except (OSError, json.JSONDecodeError):
            continue

        attachments = result.setdefault("attachments", [])
        if not any(item.get("name") == "Jenkins Console Output" for item in attachments):
            attachments.append({
                "name": "Jenkins Console Output",
                "source": source,
                "type": "text/plain",
            })

        with open(path, "w", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False)
        attached += 1
    return attached


def main():
    allure_dir = "allure-results"
    ensure_dir(allure_dir)

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
                if key in existing_ids:
                    continue
                write_result(allure_dir, suite_name, case, target_node, target_kind)
                existing_ids.add(key)
                generated += 1

    env_generated = write_environment_prepare_results(allure_dir, existing_ids)
    restore_generated = write_physical_restore_results(allure_dir, existing_ids)
    execution_generated = write_failed_execution_results(allure_dir, existing_ids)
    console_fallback = write_console_fallback_result(allure_dir, existing_ids)
    attached = attach_pending_monitor_logs(allure_dir)
    console_attached = attach_jenkins_console(allure_dir)
    print(
        f"generated allure result files from junit: {generated}, "
        f"environment prepare results: {env_generated}, "
        f"physical restore results: {restore_generated}, "
        f"failed execution results: {execution_generated}, "
        f"console fallback results: {console_fallback}, attached monitor logs: {attached}, "
        f"attached Jenkins console to results: {console_attached}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
