#!/usr/bin/env python3
"""Minimal junit -> allure-results converter for CLI branch."""
from __future__ import annotations

import glob
import json
import os
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def status_from_case(case):
    if case.find("failure") is not None:
        return "failed", case.find("failure")
    if case.find("error") is not None:
        return "broken", case.find("error")
    if case.find("skipped") is not None:
        return "skipped", case.find("skipped")
    return "passed", None


def write_attachment(results_dir: str, source: Path, name: str) -> dict | None:
    if not source.is_file():
        return None
    data = source.read_bytes()
    attach_id = uuid.uuid4().hex
    attach_path = Path(results_dir) / f"{attach_id}-attachment.txt"
    attach_path.write_bytes(data)
    return {
        "name": name,
        "source": attach_path.name,
        "type": "text/plain",
    }


def convert_junit(path: str, results_dir: str) -> int:
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError):
        return 0
    suites = [root] if root.tag == "testsuite" else root.findall(".//testsuite")
    count = 0
    now = int(time.time() * 1000)
    for suite in suites:
        suite_name = suite.attrib.get("name") or Path(path).stem
        for case in suite.findall("testcase"):
            status, detail = status_from_case(case)
            duration = 0.0
            try:
                duration = float(case.attrib.get("time") or suite.attrib.get("time") or 0)
            except ValueError:
                duration = 0.0
            duration_ms = int(max(0.0, duration) * 1000)
            result = {
                "uuid": uuid.uuid4().hex,
                "historyId": f"{suite_name}:{case.attrib.get('classname','')}:{case.attrib.get('name','')}",
                "name": case.attrib.get("name") or "unnamed",
                "fullName": f"{case.attrib.get('classname') or suite_name}.{case.attrib.get('name') or 'unnamed'}",
                "status": status,
                "stage": "finished",
                "start": now - duration_ms,
                "stop": now,
                "labels": [
                    {"name": "suite", "value": suite_name},
                    {"name": "framework", "value": "pytest"},
                    {"name": "language", "value": "python"},
                ],
                "attachments": [],
            }
            if detail is not None:
                message = (detail.attrib.get("message") or "").strip()
                text = (detail.text or "").strip()
                result["statusDetails"] = {
                    "message": message or text[:200] or status,
                    "trace": text or message,
                }
            out = Path(results_dir) / f"{result['uuid']}-result.json"
            out.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
            count += 1
    return count


def main() -> int:
    results_dir = "allure-results"
    ensure_dir(results_dir)
    total = 0
    for path in sorted(glob.glob("node-report_*.xml")):
        total += convert_junit(path, results_dir)

    # Attach collected console / execution logs to a synthetic container result.
    attachments = []
    for path, name in [
        (Path("jenkins_console.log"), "Jenkins Console Output"),
    ]:
        att = write_attachment(results_dir, path, name)
        if att:
            attachments.append(att)
    for path in sorted(glob.glob("test_execution_*.log")):
        att = write_attachment(results_dir, Path(path), Path(path).name)
        if att:
            attachments.append(att)

    if attachments or total == 0:
        container = {
            "uuid": uuid.uuid4().hex,
            "name": "CLI execution logs",
            "children": [],
            "befores": [],
            "afters": [],
            "start": int(time.time() * 1000),
            "stop": int(time.time() * 1000),
        }
        # Also emit a result that carries the log attachments for easy browsing.
        result = {
            "uuid": uuid.uuid4().hex,
            "historyId": "cli-console-log",
            "name": "完整测试日志（终端输出）",
            "fullName": "cli.console_log",
            "status": "passed" if total >= 0 else "broken",
            "stage": "finished",
            "start": int(time.time() * 1000),
            "stop": int(time.time() * 1000),
            "labels": [
                {"name": "suite", "value": "CLI"},
                {"name": "feature", "value": "console"},
            ],
            "attachments": attachments,
        }
        Path(results_dir, f"{result['uuid']}-result.json").write_text(
            json.dumps(result, ensure_ascii=False), encoding="utf-8"
        )
        Path(results_dir, f"{container['uuid']}-container.json").write_text(
            json.dumps(container, ensure_ascii=False), encoding="utf-8"
        )

    print(f"allure-results cases={total} attachments={len(attachments)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
