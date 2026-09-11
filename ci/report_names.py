"""Canonical JUnit / Allure artifact names for RAID_NVME CI.

Naming (one scheme):
  case-report_<run_key>.xml  — per-case pytest junit (DUT case dir / repo root)
  node-report.xml            — merged junit on DUT after all cases
  node-report_<IP>.xml       — Jenkins workspace copy of that node's merged junit
  allure-node-<IP>/          — temp Allure tree copied from DUT before merge
  allure-results/            — final merged Allure on Jenkins agent

Legacy aliases (still recognized by readers where noted):
  report_<run_key>.xml, report.xml, report_<IP>.xml
"""
from __future__ import annotations

import os
import re

CASE_PREFIX = "case-report_"
NODE_PREFIX = "node-report_"
NODE_MERGED = "node-report.xml"
ALLURE_FINAL = "allure-results"

_NODE_IP_RE = re.compile(r"^\d+\.\d+\.\d+\.\d+$")
_NODE_FILE_RE = re.compile(
    r"^(?:node-report_|report_)(\d+\.\d+\.\d+\.\d+)(?:_.+)?\.xml$"
)


def case_junit_name(run_key: str) -> str:
    return f"{CASE_PREFIX}{run_key}.xml"


def node_junit_name(node_ip: str, suffix: str = "") -> str:
    return f"{NODE_PREFIX}{node_ip}{suffix}.xml"


def node_merged_name() -> str:
    return NODE_MERGED


def allure_node_dirname(node_ip: str, suffix: str = "") -> str:
    return f"allure-node-{node_ip}{suffix}"


def is_node_junit_report(path: str) -> bool:
    """True for node-level merged reports on Jenkins (node-report_<IP>.xml)."""
    name = os.path.basename(path)
    if _NODE_FILE_RE.match(name):
        return True
    if name.startswith("report_") and name.endswith(".xml"):
        stem = name[len("report_") : -len(".xml")]
        ip = stem.split("_")[0]
        return bool(_NODE_IP_RE.match(ip))
    return False


def is_case_junit_report(path: str) -> bool:
    name = os.path.basename(path)
    if name.startswith(CASE_PREFIX) and name.endswith(".xml"):
        return True
    if name.startswith("report_") and name.endswith(".xml") and not is_node_junit_report(path):
        return True
    return False


def case_run_key_from_junit(path: str):
    name = os.path.basename(path)
    if name.startswith(CASE_PREFIX) and name.endswith(".xml"):
        return name[len(CASE_PREFIX) : -len(".xml")]
    if name.startswith("report_") and name.endswith(".xml") and not is_node_junit_report(path):
        return name[len("report_") : -len(".xml")]
    return None
