#!/usr/bin/env python3
import argparse
import glob
import os
import re
import xml.etree.ElementTree as ET


FAILURE_PATTERNS = (
    re.compile(r"\b(?:idle watchdog|hung|timed? out|timeout)\b", re.IGNORECASE),
    re.compile(r"\b(?:traceback|assertionerror|fatal|panic)\b", re.IGNORECASE),
    re.compile(r"\b(?:error|failed|failure|exit code|not found|no such file)\b", re.IGNORECASE),
    re.compile(r"^\s*E\s+"),
)
BENIGN_PATTERNS = (
    re.compile(r"\b0\s+(?:failed|failure|errors?)\b", re.IGNORECASE),
    re.compile(r"\b(?:failed|failure|errors?)\s*[=:]\s*0\b", re.IGNORECASE),
    re.compile(
        r"^(?:TEST_EXECUTION|ENVIRONMENT_PREPARE|PHYSICAL_RESTORE)_STATUS=",
        re.IGNORECASE,
    ),
    # Kernel headers / C comments often contain the word "error" without a real failure.
    re.compile(r"^\s*#\s*define\b"),
    re.compile(r"/\*.*\berror\b.*\*/", re.IGNORECASE),
)


def clean_line(line, max_length=260):
    line = re.sub(r"\s+", " ", line).strip()
    if len(line) > max_length:
        return line[: max_length - 3] + "..."
    return line


def is_failure_line(line):
    if not line or any(pattern.search(line) for pattern in BENIGN_PATTERNS):
        return False
    return any(pattern.search(line) for pattern in FAILURE_PATTERNS)


def extract_failure_lines(text, limit=8):
    candidates = []
    seen = set()
    for index, raw_line in enumerate(text.splitlines()):
        line = clean_line(raw_line)
        if not is_failure_line(line):
            continue
        normalized = line.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        priority = next(
            (position for position, pattern in enumerate(FAILURE_PATTERNS) if pattern.search(line)),
            len(FAILURE_PATTERNS),
        )
        candidates.append((priority, index, line))

    candidates.sort(key=lambda item: (item[0], item[1]))
    return [line for _, _, line in candidates[:limit]]


def junit_failure_lines(paths=None):
    try:
        from ci.report_metrics import is_node_junit_report
    except ModuleNotFoundError:
        from report_metrics import is_node_junit_report

    lines = []
    candidates = paths or [
        path for path in glob.glob("report_*.xml") if is_node_junit_report(path)
    ]
    for path in sorted(candidates):
        try:
            root = ET.parse(path).getroot()
        except (OSError, ET.ParseError):
            continue
        for case in root.findall(".//testcase"):
            detail = case.find("failure")
            if detail is None:
                detail = case.find("error")
            if detail is None:
                continue
            name = case.attrib.get("name", "unknown")
            message = clean_line(detail.attrib.get("message", "") or (detail.text or ""))
            lines.append(f"{os.path.basename(path)}: {name}: {message or detail.tag}")
    return lines


def log_failure_lines(paths=None):
    lines = []
    patterns = paths or (
        sorted(glob.glob("environment_prepare_*.log"))
        + sorted(glob.glob("test_execution_*.log"))
    )
    for path in patterns:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                extracted = extract_failure_lines(handle.read())
        except OSError:
            continue
        lines.extend(f"{os.path.basename(path)}: {line}" for line in extracted)
    return lines


def failure_summary(limit=8):
    combined = junit_failure_lines() + log_failure_lines()
    unique = []
    seen = set()
    for line in combined:
        normalized = line.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        unique.append(line)
        if len(unique) >= limit:
            break
    return "\n".join(f"- {line}" for line in unique)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Extract concise failure details from RAID_NVME reports and logs.")
    parser.add_argument("--output", default="failure_summary.txt")
    parser.add_argument("--limit", type=int, default=8)
    args = parser.parse_args(argv)

    summary = failure_summary(limit=max(args.limit, 1))
    with open(args.output, "w", encoding="utf-8") as handle:
        handle.write(summary)
        if summary:
            handle.write("\n")
    print(summary or "No failure summary was found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
