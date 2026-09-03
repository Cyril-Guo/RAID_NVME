"""Recover runner failures that never reached pytest's report finalization."""
import argparse
import glob
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path


def read_text(path):
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def failure_context(text):
    context = dict(item="unknown", last_item="unknown", phase="unknown", pending_command="unknown",
                   last_command="unknown", last_output="unknown", exit_code="unknown",
                   started_at_ms=0, failed_at_ms=0)
    failure_seen = False
    for line in text.splitlines():
        if "[FAILURE_CONTEXT]" in line or "[DIAGNOSTICS]" in line or "[COLLECTION_WARNING]" in line:
            continue
        code = re.search(r"TEST_EXECUTION_EXIT_CODE=(\d+)", line)
        if code:
            context["exit_code"] = code[1]
        failed_at = re.search(r"TEST_EXECUTION_FAILED_AT=(\d+)", line)
        if failed_at and not context["failed_at_ms"]:
            context["failed_at_ms"] = int(failed_at[1]) * 1000
        if "TEST_EXECUTION_STATUS=failed" in line:
            failure_seen = True
        if failure_seen or re.search(r"ERROR: .*failed with exit code", line):
            continue
        start = re.search(r"\[ITEM_START\]\s+(\S+)", line)
        end = re.search(r"\[ITEM_END\]\s+(\S+)", line)
        failed_item = re.search(r"\[ITEM_FAILED\]\s+(\S+)", line)
        end_code = re.search(r"\[ITEM_END\]\s+\S+\s+exit_code=(\d+)", line)
        if failed_item or (end and end_code and end_code[1] != "0"):
            item = (failed_item or end)[1]
            context.update(item=item, last_item=item, last_output=line[-1500:])
            failure_seen = True
            continue
        phase = re.search(r"\[PHASE\]\s+item=(\S+)\s+stage=(\S+)", line)
        command = re.search(r"\[CMD_START\]\s+(.+)", line)
        legacy = re.search(r"(?:^|\]\s+)\$\s+(.+)", line)
        if start:
            timestamp = re.search(r"started_at_ms=(\d+)", line)
            context.update(item=start[1], last_item=start[1], phase="item_start", pending_command="unknown",
                           last_command="unknown", started_at_ms=int(timestamp[1]) if timestamp else 0)
        if end and context["item"] == end[1]:
            context.update(item="unknown", phase="after_item", pending_command="unknown")
        if phase:
            context.update(item=phase[1], last_item=phase[1], phase=phase[2])
            if phase[2] == "log_collection":
                context.update(item="unknown", pending_command="unknown")
        if command or legacy:
            context["pending_command"] = context["last_command"] = (command or legacy)[1]
        if "[CMD_END]" in line or re.search(r"\[exit\]\s+-?\d+", line):
            context["pending_command"] = "unknown"
        if line.strip() and not any(marker in line for marker in (
            "TEST_EXECUTION_", "[FAILURE_CONTEXT]", "watchdog", "made no log", "[DIAGNOSTICS]",
        )):
            context["last_output"] = line[-1500:]
    return context


def execution_context(path, text=None):
    stem = Path(path).stem.removeprefix("test_execution_")
    node = stem.removesuffix("_physical")
    text = read_text(path) if text is None else text
    explicit = re.findall(r"TEST_EXECUTION_TARGET=(physical|qemu)", text)
    if explicit:
        return node, explicit[-1]
    if stem.endswith("_physical"):
        return node, "physical"
    # Older direct-physical runs used unsuffixed report names too.
    targets = set()
    for result in glob.glob("allure-results/*-result.json"):
        try:
            labels = {x["name"]: x["value"] for x in json.loads(read_text(result)).get("labels", [])}
            if labels.get("host") == node and labels.get("target") in ("physical", "qemu"):
                targets.add(labels["target"])
        except (ValueError, KeyError):
            continue
    return node, next(iter(targets)) if len(targets) == 1 else "qemu"


def report_path(log_path):
    return Path("report_" + Path(log_path).stem.removeprefix("test_execution_") + ".xml")


def item_matches(case, item):
    if item == "unknown":
        return True
    properties = {p.get("name"): p.get("value") for p in case.findall("properties/property")}
    if properties.get("run_key") == item:
        return True
    aliases = {"lawdisk": "lawdiskstress", "filesystem": "filesystemstress",
               "mix": "mix_stress", "reboot": "reboot_powercycle", "dc": "dc_powercycle"}
    function = aliases.get(item, item)
    return case.get("name") == "test_" + function or case.get("classname", "").endswith("_" + item)


def unreported_failures():
    if read_text("manual_abort.txt").strip() == "true":
        return
    for path in sorted(glob.glob("test_execution_*.log")):
        text = read_text(path)
        if "TEST_EXECUTION_STATUS=failed" not in text:
            continue
        context = failure_context(text)
        try:
            cases = ET.parse(report_path(path)).getroot().iter("testcase")
            represented = any(item_matches(case, context["item"]) and
                              (case.find("error") is not None or case.find("failure") is not None)
                              for case in cases)
        except (OSError, ET.ParseError):
            represented = False
        if not represented:
            yield path, context


def describe(context):
    return (
        f"item={context['item']} last_item={context['last_item']} phase={context['phase']} exit_code={context['exit_code']}\n"
        f"Pending command: {context['pending_command']}\n"
        f"Last command (may have completed): {context['last_command']}\n"
        f"Last output: {context['last_output']}\n"
        "No progress is an observation, not proof of a driver or hardware root cause.\n"
        "See debug log for process state, wait channel and kernel messages."
    )


def reconcile_execution_failures():
    recovered = 0
    for path, context in list(unreported_failures()):
        if context["item"] == "unknown":
            continue  # Keep a separate Test_Execution infrastructure result.
        output = report_path(path)
        try:
            root = ET.parse(output).getroot()
        except (OSError, ET.ParseError):
            root = ET.Element("testsuites")
        if root.tag == "testsuite":
            parent = ET.Element("testsuites")
            parent.append(root)
            root = parent
        suite = ET.SubElement(root, "testsuite", name=context["item"])
        elapsed = max(0, context["failed_at_ms"] - context["started_at_ms"]) / 1000 if context["started_at_ms"] else 0
        case = ET.SubElement(suite, "testcase", name="test_" + context["item"],
                             classname="smoke_execution." + context["item"], time=str(elapsed))
        properties = ET.SubElement(case, "properties")
        for key, value in (("run_key", context["item"]), ("execution_log", path),
                           ("started_at_ms", str(context["started_at_ms"]))):
            ET.SubElement(properties, "property", name=key, value=value)
        summary = f"{context['item']}: execution failed (exit {context['exit_code']}), phase={context['phase']}"
        ET.SubElement(case, "error", message=summary, type="RunnerFailure").text = (
            summary + "\n" + describe(context) + "\n\n" + read_text(path)[-12000:]
        )
        for element in [*root.findall(".//testsuite"), root]:
            cases = list(element.iter("testcase"))
            for key, tag in (("tests", None), ("errors", "error"), ("failures", "failure"), ("skipped", "skipped")):
                element.set(key, str(sum(tag is None or c.find(tag) is not None for c in cases)))
        ET.ElementTree(root).write(output, encoding="utf-8", xml_declaration=True)
        print(f"[REPORT_RECOVERY] {summary}; report={output}")
        recovered += 1
    return recovered


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--describe", required=True)
    args = parser.parse_args()
    for line in describe(failure_context(read_text(args.describe))).splitlines():
        print("[FAILURE_CONTEXT] " + line)
