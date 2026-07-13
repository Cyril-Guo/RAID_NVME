import os
import sys
import xml.etree.ElementTree as ET

import pytest


TEST_ITEMS = {
    "reboot": "test_items/test_smoke_01_reboot.py",
    "dc": "test_items/test_smoke_02_dc.py",
    "lawdisk": "test_items/test_smoke_03_lawdisk.py",
    "filesystem": "test_items/test_smoke_04_filesystem.py",
    "mix": "test_items/test_smoke_05_mix.py",
}

ITEM_PARAMS = {
    "reboot": ["FIO_CYCLES", "IGNORE_ERROR", "FIO_DISKS", "STRESS_MONITOR", "MONITOR_RUNTIME"],
    "dc": ["FIO_CYCLES", "IGNORE_ERROR", "FIO_DISKS", "STRESS_MONITOR", "MONITOR_RUNTIME"],
    "lawdisk": ["IGNORE_ERROR", "FIO_DISKS", "STRESS_MONITOR", "MONITOR_RUNTIME"],
    "filesystem": ["IGNORE_ERROR", "FIO_DISKS", "STRESS_MONITOR", "MONITOR_RUNTIME"],
    "mix": ["IGNORE_ERROR", "FIO_DISKS", "STRESS_MONITOR", "MONITOR_RUNTIME"],
}

ALL_PARAM_KEYS = sorted({key for keys in ITEM_PARAMS.values() for key in keys})

ITEMS_FILE = "test_items.txt"
ALLURE_DIR = "allure-results"
JUNIT_FINAL = "report.xml"


def parse_items_file(path):
    selected = []
    params_map = {}
    current = None
    selection_items = []

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
                if current != "selection":
                    params_map.setdefault(current, {})
                continue
            if "=" not in line or current is None:
                continue

            key, value = [part.strip() for part in line.split("=", 1)]
            enabled = value.lower() in ("yes", "y", "true", "1", "on")
            if current == "selection":
                if enabled:
                    selection_items.append(key.strip().lower())
            elif key.lower() == "enable":
                if value.lower() == "yes":
                    selected.append(current)
            else:
                params_map[current][key] = value

    if selection_items:
        selected = selection_items

    return selected, params_map


def run_single_item(item, params, clean_allure):
    test_file = TEST_ITEMS[item]
    allowed = ITEM_PARAMS.get(item, [])

    for key in ALL_PARAM_KEYS:
        os.environ.pop(key, None)

    print("\n" + "=" * 60)
    print(f"[ITEM] {item} -> {test_file}")

    for key, value in params.items():
        if key not in allowed:
            print(f"  [SKIP] {key}={value} (unused by {item})")
            continue
        os.environ[key] = value
        print(f"  [CONFIG] {key}={value}")

    pytest_args = ["-v", "-s", "--tb=short", f"--alluredir={ALLURE_DIR}"]
    if clean_allure:
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


def validate_selection(selected):
    invalid = [item for item in selected if item not in TEST_ITEMS]
    missing = [item for item in selected if item in TEST_ITEMS and not os.path.exists(TEST_ITEMS[item])]
    return invalid, missing


def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    items_path = os.path.join(base_dir, ITEMS_FILE)

    selected, params_map = parse_items_file(items_path)
    invalid, missing = validate_selection(selected)

    if invalid:
        print(f"[ERROR] Unknown test items: {invalid}")
        print(f"[ERROR] Available items: {list(TEST_ITEMS.keys())}")
        sys.exit(2)

    if missing:
        print(f"[ERROR] Missing test files: {missing}")
        sys.exit(2)

    selected_set = set(selected)
    run_order = [item for item in TEST_ITEMS if item in selected_set]

    if not run_order:
        print(f"[ERROR] No valid test items selected in {ITEMS_FILE}.")
        sys.exit(2)

    print(f"Selected test items: {run_order}")

    exit_codes = []
    for index, item in enumerate(run_order):
        exit_codes.append(
            run_single_item(item, params_map.get(item, {}), clean_allure=(index == 0))
        )

    merge_junit_reports(run_order, os.path.join(base_dir, JUNIT_FINAL))
    sys.exit(max(exit_codes) if exit_codes else 0)


if __name__ == "__main__":
    main()
