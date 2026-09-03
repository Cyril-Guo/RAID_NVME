import glob
import json
import os
import re
import time
import uuid
import xml.etree.ElementTree as ET

try:
    from ci.build_status import console_was_manually_aborted
    from ci.extract_failure_summary import extract_failure_lines
    from ci.report_metrics import execution_log_has_explicit_failure, is_node_junit_report
    from ci.report_identity import native_case_exists, normalize_results, discard_junit_placeholders, case_run_key
    from ci.allure_fixture_cleanup import flatten_fixtures
    from ci.report_artifacts import attach_workspace_artifacts
except ModuleNotFoundError:
    from build_status import console_was_manually_aborted
    from extract_failure_summary import extract_failure_lines
    from report_metrics import execution_log_has_explicit_failure, is_node_junit_report
    from report_identity import native_case_exists, normalize_results, discard_junit_placeholders, case_run_key
    from allure_fixture_cleanup import flatten_fixtures
    from report_artifacts import attach_workspace_artifacts


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


def testcase_duration_seconds(case, suite=None):
    for source in (case, suite):
        if source is None:
            continue
        raw = source.attrib.get("time")
        if raw in (None, ""):
            continue
        try:
            return max(0.0, float(raw))
        except ValueError:
            continue
    return 0.0


def apply_result_timing(result, duration_seconds=0.0):
    duration_ms = int(max(0.0, float(duration_seconds)) * 1000)
    stop_ms = int(time.time() * 1000)
    result["stop"] = stop_ms
    result["start"] = stop_ms - duration_ms
    return result


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


def result_matches_item(result, item, run_key=None):
    if run_key:
        labels = _result_labels(result)
        labeled = labels.get("run_key")
        if labeled:
            return labeled == run_key
        candidates = [labels.get("package", ""), labels.get("suite", "")]
        if run_key in candidates:
            return True
        if any("__" in value for value in candidates):
            return False
    parts = [
        str(result.get(key, "")).lower()
        for key in ("name", "fullName", "historyId", "testCaseId")
    ]
    for label in result.get("labels") or []:
        parts.append(str(label.get("value", "")).lower())
    text = " ".join(parts)
    aliases = {
        "lawdisk": ("lawdisk", "lawdiskstress"),
        "filesystem": ("filesystem", "filesystemstress"),
        "mix": ("mix", "mix_stress"),
        "reboot": ("reboot", "reboot_powercycle"),
        "dc": ("dc", "dc_powercycle"),
        "basic_io": ("basic_io",),
        "basic_rebuild_io": ("basic_rebuild_io",),
        "random_io": ("random_io", "randomio"),
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
            if entry.get("scope") != "node" and not result_matches_item(result, entry.get("item", ""), run_key=entry.get("run_key")):
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
    """Return FIO summary lines plus concrete fio error detail blocks when present."""
    lines = []
    seen = set()
    in_detail = False
    for raw in (text or "").splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if not line:
            continue
        if "----- FIO error detail begin" in line:
            in_detail = True
            key = line.lower()
            if key not in seen:
                seen.add(key)
                lines.append(line)
            continue
        if "----- FIO error detail end" in line:
            key = line.lower()
            if key not in seen:
                seen.add(key)
                lines.append(line)
            in_detail = False
            continue
        if in_detail:
            key = line.lower()
            if key not in seen:
                seen.add(key)
                lines.append(line)
            continue
        if not FIO_FAILURE_LINE_RE.search(line):
            continue
        key = line.lower()
        if key in seen:
            continue
        seen.add(key)
        lines.append(line)
    return lines


def write_result(allure_dir, suite_name, case, target_node="", target_kind="", suite=None):
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
            {"name": "run_key", "value": case_run_key(case)},
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
                    "name": "FIO Failure Detail",
                    "source": source,
                    "type": "text/plain",
                }
            ]
        else:
            result["statusDetails"] = {
                "message": message or status,
                "trace": trace or message or status,
            }

    apply_result_timing(result, testcase_duration_seconds(case, suite))

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
        apply_result_timing(result)

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


def report_has_failures_or_errors(target_node, target_kind):
    path = f"report_{target_node}.xml"
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return False
    return root.find(".//failure") is not None or root.find(".//error") is not None


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
    # Empty or truncated logs from ABORTED builds never write a terminal status.
    return (not (text or "").strip()) or ("aborted" in lowered) or ("idle watchdog fired" in lowered)


def write_failed_execution_results(allure_dir, existing_ids):
    manually_aborted = console_was_manually_aborted()
    generated = 0
    for path in sorted(glob.glob("test_execution_*.log")):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                text = handle.read()
        except OSError:
            continue

        if manually_aborted and not execution_log_has_explicit_failure(text):
            continue
        if not execution_log_needs_result(text):
            continue

        target_node, target_kind = execution_log_context(path)
        if report_has_testcases(target_node, target_kind) and report_has_failures_or_errors(
            target_node, target_kind
        ):
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
        apply_result_timing(result)
        with open(os.path.join(allure_dir, f"{test_uuid}-result.json"), "w", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False)
        existing_ids.add(key)
        generated += 1
    return generated


def write_console_fallback_result(allure_dir, existing_ids, console_path="jenkins_console.log"):
    """Ensure ABORTED/infra builds still produce an Allure case when no other results exist."""
    if console_was_manually_aborted(console_path):
        return 0
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

    source = f"{uuid.uuid4()}-terminal.log"
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
                "name": "终端输出",
                "source": source,
                "type": "text/plain",
            }
        ],
        "statusDetails": {
            "message": summary[0] if summary else default_message,
            "trace": "\n".join(summary or text.splitlines()[-120:] or [default_message]),
        },
    }
    apply_result_timing(result)
    with open(os.path.join(allure_dir, f"{test_uuid}-result.json"), "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False)
    existing_ids.add(key)
    return 1


CONSOLE_ATTACHMENT_ALIASES = {
    "终端输出",
    "终端完整输出",
    "Jenkins Console Output",
}
FULL_CONSOLE_ATTACHMENT_NAME = "完整 Jenkins Console"
FULL_CONSOLE_SOURCE = "jenkins_console_full.log"
REPORT_SECTION_NAMES = ("终端输出", "测试结果", "日志收集")
RESULT_ATTACHMENT_NAMES = {
    "准备/收尾异常",
    "测试步骤明细",
    "报错日志",
    "执行结果",
    "FIO 故障摘要",
    "FIO Failure Detail",
    "测试结果汇总",
}


def _read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return ""


def _result_labels(result):
    return {label.get("name"): label.get("value") for label in result.get("labels") or []}


def attach_jenkins_console(allure_dir, console_path="jenkins_console.log"):
    result_paths = sorted(glob.glob(os.path.join(allure_dir, "*-result.json")))
    if not result_paths or not os.path.isfile(console_path):
        return 0
    full_console = _read_text(console_path)
    if not full_console.strip():
        return 0

    console_target = os.path.join(allure_dir, FULL_CONSOLE_SOURCE)
    with open(console_path, "rb") as src, open(console_target, "wb") as dst:
        dst.write(src.read())
    attached = 0

    for path in result_paths:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                result = json.load(handle)
        except (OSError, json.JSONDecodeError):
            continue

        attachments = result.setdefault("attachments", [])
        attachments = [
            item
            for item in attachments
            if item.get("name") != FULL_CONSOLE_ATTACHMENT_NAME
            and item.get("source") != FULL_CONSOLE_SOURCE
        ]
        attachments.append(
            {
                "name": FULL_CONSOLE_ATTACHMENT_NAME,
                "source": FULL_CONSOLE_SOURCE,
                "type": "text/plain",
            }
        )
        result["attachments"] = attachments
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False)
        attached += 1
    return attached


def _dedupe_attachments(attachments):
    unique = []
    seen = set()
    for attachment in attachments:
        key = (attachment.get("source"), attachment.get("name"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(attachment)
    return unique


def _write_section_text(allure_dir, source, text):
    with open(os.path.join(allure_dir, source), "w", encoding="utf-8") as handle:
        handle.write(text)
        if text and not text.endswith("\n"):
            handle.write("\n")


def _result_attachment(allure_dir, result):
    status = result.get("status") or "unknown"
    details = result.get("statusDetails") or {}
    message = details.get("message") or ("Test passed" if status == "passed" else status)
    trace = details.get("trace") or ""
    lines = [f"status={status}", f"message={message}"]
    if trace and trace.strip() != str(message).strip():
        lines.extend(["", "error_log:", trace])
    source = f"{result.get('uuid') or uuid.uuid4()}-test-result.log"
    _write_section_text(allure_dir, source, "\n".join(lines))
    return {
        "name": "报错日志" if status in {"failed", "broken"} else "执行结果",
        "source": source,
        "type": "text/plain",
    }


def _placeholder_attachment(allure_dir, result, suffix, name, text):
    source = f"{result.get('uuid') or uuid.uuid4()}-{suffix}.txt"
    _write_section_text(allure_dir, source, text)
    return {"name": name, "source": source, "type": "text/plain"}


def _is_result_attachment(attachment):
    name = str(attachment.get("name") or "")
    return name in RESULT_ATTACHMENT_NAMES or name.startswith(("测试结果", "数据一致性结果"))


def _section_step(name, status, attachments, result):
    stop = result.get("stop") or int(time.time() * 1000)
    return {
        "name": name,
        "status": status,
        "stage": "finished",
        "start": stop,
        "stop": stop,
        "attachments": attachments,
    }


def organize_result_sections(allure_dir):
    """Render console, result and debug artifacts as three sibling Allure steps."""
    organized = 0
    for path in sorted(glob.glob(os.path.join(allure_dir, "*-result.json"))):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                result = json.load(handle)
        except (OSError, json.JSONDecodeError):
            continue

        pool = list(result.pop("attachments", []) or [])
        def drain(step):
            pool.extend(step.get("attachments") or [])
            for child in step.get("steps") or []:
                drain(child)
        original_steps = result.get("steps") or []
        for step in original_steps:
            drain(step)
        unmanaged = [step for step in original_steps if step.get("name") not in REPORT_SECTION_NAMES]
        if unmanaged:
            pool.append(_placeholder_attachment(allure_dir, result, "original-steps", "测试步骤明细",
                        json.dumps(unmanaged, ensure_ascii=False, indent=2)))

        terminal = []
        result_logs = []
        debug_logs = []
        missing = []
        for attachment in _dedupe_attachments(pool):
            name = attachment.get("name")
            source = attachment.get("source")
            if not source or "/" in source or "\\" in source or not os.path.isfile(os.path.join(allure_dir, source)):
                missing.append(f"{name}: source={source}")
                continue
            if (
                name in {FULL_CONSOLE_ATTACHMENT_NAME, "Console 采集说明"}
                or source == FULL_CONSOLE_SOURCE
                or str(source or "").endswith("-jenkins-console-missing.txt")
            ):
                terminal.append(attachment)
            elif name in CONSOLE_ATTACHMENT_ALIASES:
                # Legacy pytest attachments used this misleading name. A fresh run
                # writes them as "FIO 执行日志"; do not show them as Jenkins Console.
                renamed = dict(attachment)
                renamed["name"] = "FIO 执行日志（旧版）"
                debug_logs.append(renamed)
            elif _is_result_attachment(attachment):
                result_logs.append(attachment)
            else:
                debug_logs.append(attachment)

        if missing:
            debug_logs.append(_placeholder_attachment(allure_dir, result, "missing-artifacts", "附件缺失说明",
                "Referenced files were not recovered from the target. They are not downloadable.\n"
                "Check the node collection log for timeout / SCP errors.\n\n" + "\n".join(missing)))

        if not terminal:
            terminal.append(
                _placeholder_attachment(
                    allure_dir,
                    result,
                    "jenkins-console-missing",
                    "Console 采集说明",
                    "Jenkins Console was not available when the Allure report was assembled.",
                )
            )
        elif any(
            item.get("name") == FULL_CONSOLE_ATTACHMENT_NAME for item in terminal
        ):
            terminal = [item for item in terminal if item.get("name") != "Console 采集说明"]
        result_logs.insert(0, _result_attachment(allure_dir, result))
        real_debug_logs = [
            item for item in debug_logs if item.get("name") != "日志收集说明"
        ]
        if real_debug_logs:
            debug_logs = real_debug_logs
        else:
            debug_logs = []
            debug_logs.append(
                _placeholder_attachment(
                    allure_dir,
                    result,
                    "debug-log-empty",
                    "日志收集说明",
                    "No related debug log was recovered for this test case.\n"
                    "Collection may have been interrupted or copying may have failed; "
                    "this is not evidence that no device error occurred.\n"
                    "Check the node execution / collection log and Jenkins Console.",
                )
            )

        status = result.get("status") or "unknown"
        has_debug_files = any(a.get("name") not in {"日志收集说明", "附件缺失说明"} for a in debug_logs)
        managed_steps = [
            _section_step("终端输出", "passed" if terminal else "skipped", terminal, result),
            _section_step("测试结果", status, _dedupe_attachments(result_logs), result),
            _section_step(
                "日志收集",
                "passed" if has_debug_files else "skipped",
                _dedupe_attachments(debug_logs),
                result,
            ),
        ]
        result["steps"] = managed_steps
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False)
        organized += 1
    return organized


def main():
    allure_dir = "allure-results"
    ensure_dir(allure_dir)
    flatten_fixtures(allure_dir)
    normalize_results(allure_dir)
    discard_junit_placeholders(allure_dir)

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
                if key in existing_ids or native_case_exists(allure_dir, case, target_node):
                    continue
                write_result(allure_dir, suite_name, case, target_node, target_kind, suite=suite)
                existing_ids.add(key)
                generated += 1

    env_generated = write_environment_prepare_results(allure_dir, existing_ids)
    restore_generated = write_physical_restore_results(allure_dir, existing_ids)
    execution_generated = write_failed_execution_results(allure_dir, existing_ids)
    console_fallback = write_console_fallback_result(allure_dir, existing_ids)
    normalize_results(allure_dir)
    workspace_attached = attach_workspace_artifacts(allure_dir)
    attached = attach_pending_monitor_logs(allure_dir)
    console_attached = attach_jenkins_console(allure_dir)
    organized = organize_result_sections(allure_dir)
    print(
        f"generated allure result files from junit: {generated}, "
        f"environment prepare results: {env_generated}, "
        f"physical restore results: {restore_generated}, "
        f"failed execution results: {execution_generated}, "
        f"console fallback results: {console_fallback}, attached monitor logs: {attached}, "
        f"attached downloaded bundles: {workspace_attached}, "
        f"attached Jenkins console to results: {console_attached}, "
        f"organized report sections: {organized}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
