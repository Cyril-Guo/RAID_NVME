import glob
import os
import json
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
import importlib.util

import pytest


ALLOWED_PARAM_KEYS = (
    "FIO_CYCLES",
    "IGNORE_ERROR",
    "FIO_DISKS",
    "STRESS_MONITOR",
    "MONITOR_RUNTIME",
)
ALL_PARAM_KEYS = sorted(ALLOWED_PARAM_KEYS)

ITEMS_FILE = "test_items.txt"
ITEMS_DIR = "test_items"
ALLURE_DIR = "allure-results"
JUNIT_FINAL = "report.xml"

_SMOKE_NAME_RE = re.compile(r"^test_smoke_\d+_(.+)\.py$", re.IGNORECASE)
_TEST_NAME_RE = re.compile(r"^test_(.+)\.py$", re.IGNORECASE)
_SKIP_NAME_RE = re.compile(r"(^__init__\.py$|_common\.py$|^powercycle_launch\.py$)", re.IGNORECASE)


def item_name_from_filename(filename):
    """Map test_smoke_03_lawdisk.py -> lawdisk, test_foo.py -> foo."""
    if _SKIP_NAME_RE.search(filename):
        return None
    match = _SMOKE_NAME_RE.match(filename)
    if match:
        return match.group(1).strip().lower()
    match = _TEST_NAME_RE.match(filename)
    if match:
        name = match.group(1).strip().lower()
        if name and not name.endswith("_common"):
            return name
    return None


def discover_test_items(items_dir=None):
    """Scan test_items/test_*.py and return {item_name: relative_path}."""
    if items_dir is None:
        items_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), ITEMS_DIR)

    discovered = {}
    pattern = os.path.join(items_dir, "test_*.py")
    for path in sorted(glob.glob(pattern)):
        filename = os.path.basename(path)
        name = item_name_from_filename(filename)
        if not name:
            continue
        rel_path = os.path.join(ITEMS_DIR, filename).replace("\\", "/")
        if name in discovered:
            raise ValueError(
                f"Duplicate test item name '{name}': {discovered[name]} and {rel_path}"
            )
        discovered[name] = rel_path
    return discovered


TEST_ITEMS = discover_test_items()


def parse_items_file(path):
    """Parse whitelist + [defaults] + optional per-item overrides.

    Lines before the first [section] are the run list (one item name per line).
    Empty whitelist means run nothing.
    """
    selected = []
    defaults = {}
    overrides = {}
    current = None  # None = whitelist mode

    if not os.path.exists(path):
        print(f"[ERROR] Missing config file: {path}")
        sys.exit(2)

    with open(path, "r", encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("[") and line.endswith("]"):
                current = line[1:-1].strip().lower()
                if current and current != "defaults":
                    overrides.setdefault(current, {})
                continue

            if current is None:
                # Whitelist entry: bare name, or "name = yes" for accidental old style.
                if "=" in line:
                    key, value = [part.strip() for part in line.split("=", 1)]
                    enabled = value.lower() in ("yes", "y", "true", "1", "on")
                    if enabled:
                        selected.append(key.lower())
                else:
                    selected.append(line.lower())
                continue

            if "=" not in line:
                continue
            key, value = [part.strip() for part in line.split("=", 1)]
            if current == "defaults":
                defaults[key] = value
            else:
                overrides[current][key] = value

    params_map = {}
    for item in set(selected) | set(overrides):
        params_map[item] = dict(defaults)
        params_map[item].update(overrides.get(item, {}))

    return selected, params_map


def run_single_item(item, params, clean_allure, test_items=None):
    catalog = test_items if test_items is not None else TEST_ITEMS
    test_file = catalog[item]

    for key in ALL_PARAM_KEYS:
        os.environ.pop(key, None)

    print("\n" + "=" * 60)
    print(f"[ITEM] {item} -> {test_file}")

    for key, value in params.items():
        if key not in ALLOWED_PARAM_KEYS:
            print(f"  [SKIP] {key}={value} (unused by {item})")
            continue
        os.environ[key] = value
        print(f"  [CONFIG] {key}={value}")

    pytest_args = ["-v", "-s", "--tb=short"]
    if importlib.util.find_spec("allure_pytest") is not None:
        pytest_args.append(f"--alluredir={ALLURE_DIR}")
    elif clean_allure:
        shutil.rmtree(ALLURE_DIR, ignore_errors=True)

    if clean_allure and importlib.util.find_spec("allure_pytest") is not None:
        pytest_args.append("--clean-alluredir")
    pytest_args.extend([f"--junitxml=report_{item}.xml", test_file])

    return int(pytest.main(pytest_args))


def merge_junit_reports(items, out_path):
    merged_root = ET.Element("testsuites")
    for item in items:
        part = f"report_{item}.xml"
        if not os.path.exists(part):
            continue
        try:
            root = ET.parse(part).getroot()
        except ET.ParseError:
            continue

        if root.tag == "testsuites":
            for suite in root.findall("testsuite"):
                merged_root.append(suite)
        elif root.tag == "testsuite":
            merged_root.append(root)

    ET.ElementTree(merged_root).write(out_path, encoding="utf-8", xml_declaration=True)


def validate_selection(selected, test_items=None, base_dir=None):
    catalog = test_items if test_items is not None else TEST_ITEMS
    root = base_dir or os.path.dirname(os.path.abspath(__file__))
    invalid = [item for item in selected if item not in catalog]
    missing = [
        item
        for item in selected
        if item in catalog and not os.path.exists(os.path.join(root, catalog[item]))
    ]
    return invalid, missing


def stress_monitor_enabled(params):
    return params.get("STRESS_MONITOR", "").strip().lower() == "yes"


def monitor_paths(base_dir):
    monitor_dir = os.path.join(base_dir, "Stress_Monitor")
    monitor_main = os.path.join(monitor_dir, "main.py")
    monitor_log = os.path.join(monitor_dir, "monitor_log")
    return monitor_main, monitor_log


def clean_monitor_log(base_dir):
    _, monitor_log = monitor_paths(base_dir)
    if os.path.exists(monitor_log):
        shutil.rmtree(monitor_log, ignore_errors=True)


def monitor_running(monitor_main):
    result = subprocess.run(
        ["pgrep", "-f", monitor_main],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def stop_monitor_for_item(base_dir, wait_seconds=30):
    monitor_main, _ = monitor_paths(base_dir)
    subprocess.run(
        ["pkill", "-TERM", "-f", monitor_main],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    for _ in range(wait_seconds):
        if not monitor_running(monitor_main):
            return
        time.sleep(1)

    print(f"[WARN] Stress monitor still running after TERM; sending KILL: {monitor_main}")
    subprocess.run(
        ["pkill", "-KILL", "-f", monitor_main],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    for _ in range(5):
        if not monitor_running(monitor_main):
            return
        time.sleep(1)


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


def attach_monitor_archive_to_result(item, base_dir, archive_name):
    allure_dir = os.path.join(base_dir, ALLURE_DIR)
    attachment = {
        "name": "monitor_log_{}".format(item),
        "source": archive_name,
        "type": "application/gzip",
    }

    for name in os.listdir(allure_dir):
        if not name.endswith("-result.json"):
            continue
        path = os.path.join(allure_dir, name)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                result = json.load(handle)
        except (OSError, json.JSONDecodeError):
            continue
        if not result_matches_item(result, item):
            continue

        attachments = result.setdefault("attachments", [])
        if not any(existing.get("source") == archive_name for existing in attachments):
            attachments.append(attachment)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False)
        return True

    sidecar = os.path.join(allure_dir, "monitor_attachments.json")
    try:
        with open(sidecar, "r", encoding="utf-8") as handle:
            pending = json.load(handle)
    except (OSError, json.JSONDecodeError):
        pending = []
    pending.append({"item": item, "attachment": attachment})
    with open(sidecar, "w", encoding="utf-8") as handle:
        json.dump(pending, handle, ensure_ascii=False)
    return False


def add_allure_monitor_archive(item, base_dir):
    _, monitor_log = monitor_paths(base_dir)
    if not os.path.isdir(monitor_log):
        return

    allure_dir = os.path.join(base_dir, ALLURE_DIR)
    os.makedirs(allure_dir, exist_ok=True)

    archive_name = "monitor_log_{}.tar.gz".format(item)
    base_name = os.path.join(allure_dir, "monitor_log_{}".format(item))
    shutil.make_archive(base_name, "gztar", root_dir=os.path.dirname(monitor_log), base_dir=os.path.basename(monitor_log))
    attach_monitor_archive_to_result(item, base_dir, archive_name)


def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    items_path = os.path.join(base_dir, ITEMS_FILE)
    test_items = discover_test_items(os.path.join(base_dir, ITEMS_DIR))

    selected, params_map = parse_items_file(items_path)
    invalid, missing = validate_selection(selected, test_items=test_items, base_dir=base_dir)

    if invalid:
        print(f"[ERROR] Unknown test items: {invalid}")
        print(f"[ERROR] Available items: {list(test_items.keys())}")
        sys.exit(2)

    if missing:
        print(f"[ERROR] Missing test files: {missing}")
        sys.exit(2)

    # Preserve whitelist order from test_items.txt.
    run_order = [item for item in selected if item in test_items]

    if not run_order:
        print(f"[ERROR] No valid test items selected in {ITEMS_FILE}.")
        print(f"[ERROR] Add item names (one per line) above [defaults]. Available: {list(test_items.keys())}")
        sys.exit(2)

    print(f"Selected test items: {run_order}")
    print(f"Discovered test items: {list(test_items.keys())}")

    exit_codes = []
    executed_items = []
    junit_final = os.path.join(base_dir, JUNIT_FINAL)
    for index, item in enumerate(run_order):
        params = params_map.get(item, {})
        monitor_enabled = stress_monitor_enabled(params)
        print(f"[ITEM_START] {item}")
        exit_code = 2
        try:
            if monitor_enabled:
                clean_monitor_log(base_dir)
            exit_code = run_single_item(
                item, params, clean_allure=(index == 0), test_items=test_items
            )
            print(f"[ITEM_END] {item} exit_code={exit_code}")
        finally:
            if monitor_enabled:
                stop_monitor_for_item(base_dir)
                try:
                    add_allure_monitor_archive(item, base_dir)
                except Exception as exc:
                    print(f"[WARN] Failed to archive monitor log for {item}: {exc}")
            executed_items.append(item)
            exit_codes.append(exit_code)
            # Merge after every item so idle/external kills still keep completed reports.
            merge_junit_reports(executed_items, junit_final)

        if exit_code != 0:
            print(f"[FAIL_FAST] Stop after {item} failed with exit_code={exit_code}")
            break

    sys.exit(max(exit_codes) if exit_codes else 0)


if __name__ == "__main__":
    main()
