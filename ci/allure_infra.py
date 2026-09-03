"""Allure records for failures outside pytest cases."""
import glob
import json
import os
import uuid

try:
    from ci.extract_failure_summary import extract_failure_lines
    from ci.execution_failure import execution_context, unreported_failures, describe
except ModuleNotFoundError:
    from extract_failure_summary import extract_failure_lines
    from execution_failure import execution_context, unreported_failures, describe


def context_label(kind):
    return "Physical" if kind == "physical" else "QEMU"


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


def write_failed_execution_results(allure_dir, existing_ids):
    generated = 0
    for path, context in unreported_failures():
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                text = handle.read()
        except OSError:
            continue

        if "TEST_EXECUTION_STATUS=failed" not in text:
            continue

        target_node, target_kind = execution_context(path)
        key = f"Test_Execution::{target_node}::{target_kind}"
        if key in existing_ids:
            continue

        source = f"{uuid.uuid4()}-test-execution.log"
        with open(path, "rb") as src, open(os.path.join(allure_dir, source), "wb") as dst:
            dst.write(src.read())

        summary = extract_failure_lines(text)
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
                "message": summary[0] if summary else "Remote test execution failed",
                "trace": describe(context) + "\n\n" + "\n".join(summary or text.splitlines()[-120:]),
            },
        }
        with open(os.path.join(allure_dir, f"{test_uuid}-result.json"), "w", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False)
        existing_ids.add(key)
        generated += 1
    return generated
