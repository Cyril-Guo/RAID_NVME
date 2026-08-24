import os
import json
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
import importlib.util

import pytest


TEST_ITEMS = {
    "reboot": "test_items/test_smoke_01_reboot.py",
    "dc": "test_items/test_smoke_02_dc.py",
    "lawdisk": "test_items/test_smoke_03_lawdisk.py",
    "filesystem": "test_items/test_smoke_04_filesystem.py",
    "mix": "test_items/test_smoke_05_mix.py",
    "basic_io": "test_items/test_smoke_06_basic_io.py",
    "basic_rebuild_io": "test_items/test_smoke_07_basic_rebuild_io.py",
    "multi_raid_io": "test_items/test_smoke_08_multi_raid_io.py",
    "multi_raid_degraded_io": "test_items/test_smoke_09_multi_raid_degraded_io.py",
}

ITEM_PARAMS = {
    "reboot": ["FIO_CYCLES", "IGNORE_ERROR", "FIO_DISKS", "STRESS_MONITOR", "MONITOR_RUNTIME"],
    "dc": ["FIO_CYCLES", "IGNORE_ERROR", "FIO_DISKS", "STRESS_MONITOR", "MONITOR_RUNTIME"],
    "lawdisk": ["IGNORE_ERROR", "FIO_DISKS", "STRESS_MONITOR", "MONITOR_RUNTIME"],
    "filesystem": ["IGNORE_ERROR", "FIO_DISKS", "STRESS_MONITOR", "MONITOR_RUNTIME"],
    "mix": ["IGNORE_ERROR", "FIO_DISKS", "STRESS_MONITOR", "MONITOR_RUNTIME"],
    "basic_io": ["IGNORE_ERROR", "FIO_DISKS", "STRESS_MONITOR", "MONITOR_RUNTIME", "LOGICAL_BLOCK_SIZE"],
    "basic_rebuild_io": ["IGNORE_ERROR", "FIO_DISKS", "STRESS_MONITOR", "MONITOR_RUNTIME", "LOGICAL_BLOCK_SIZE"],
    "multi_raid_io": ["IGNORE_ERROR", "FIO_DISKS", "STRESS_MONITOR", "MONITOR_RUNTIME", "LOGICAL_BLOCK_SIZE"],
    "multi_raid_degraded_io": ["IGNORE_ERROR", "FIO_DISKS", "STRESS_MONITOR", "MONITOR_RUNTIME", "LOGICAL_BLOCK_SIZE"],
}

ALL_PARAM_KEYS = sorted({key for keys in ITEM_PARAMS.values() for key in keys})

ITEMS_FILE = "test_items.txt"
ALLURE_DIR = "allure-results"
JUNIT_FINAL = "report.xml"
CASES_DIR = "cases"


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


def prepare_case_workdir(repo_root, item):
    """Create an isolated per-case tree under cases/<item>.

    Shared read-only content is symlinked; IO_Stress is copied so each case
    keeps its own FIO/MachineCheck logs and does not overwrite siblings.
    """
    case_dir = os.path.join(repo_root, CASES_DIR, item)
    if os.path.isdir(case_dir):
        shutil.rmtree(case_dir)
    os.makedirs(case_dir, exist_ok=True)

    skip_names = {
        CASES_DIR,
        ".git",
        ALLURE_DIR,
        JUNIT_FINAL,
        ".pytest_cache",
        "__pycache__",
    }
    for name in sorted(os.listdir(repo_root)):
        if name in skip_names:
            continue
        if name.startswith("report_") and name.endswith(".xml"):
            continue
        src = os.path.join(repo_root, name)
        dst = os.path.join(case_dir, name)
        if name == "IO_Stress":
            shutil.copytree(
                src,
                dst,
                ignore=shutil.ignore_patterns("log", "__pycache__", "*.pyc", ".pytest_cache"),
                symlinks=True,
            )
            os.makedirs(os.path.join(dst, "log"), exist_ok=True)
            continue
        if os.path.isdir(src) or os.path.isfile(src):
            try:
                os.symlink(src, dst, target_is_directory=os.path.isdir(src))
            except OSError:
                # Windows without symlink privilege falls back to copy.
                if os.path.isdir(src):
                    shutil.copytree(
                        src,
                        dst,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"),
                        symlinks=True,
                    )
                else:
                    shutil.copy2(src, dst)
    return case_dir


def collect_case_outputs(case_dir, repo_root, item):
    """Copy per-case junit/allure artifacts back to the build root for Jenkins collect."""
    src_report = os.path.join(case_dir, f"report_{item}.xml")
    dst_report = os.path.join(repo_root, f"report_{item}.xml")
    if os.path.isfile(src_report):
        shutil.copy2(src_report, dst_report)

    src_allure = os.path.join(case_dir, ALLURE_DIR)
    dst_allure = os.path.join(repo_root, ALLURE_DIR)
    if not os.path.isdir(src_allure):
        return
    os.makedirs(dst_allure, exist_ok=True)
    for name in os.listdir(src_allure):
        src = os.path.join(src_allure, name)
        dst = os.path.join(dst_allure, name)
        # Allure artifact names are UUID-based; keep names so attachment links stay valid.
        if os.path.exists(dst):
            continue
        if os.path.isdir(src):
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)


def run_single_item(item, params, clean_allure, work_dir=None):
    test_file = TEST_ITEMS[item]
    allowed = ITEM_PARAMS.get(item, [])
    work_dir = work_dir or os.getcwd()

    for key in ALL_PARAM_KEYS:
        os.environ.pop(key, None)

    print("\n" + "=" * 60)
    print(f"[ITEM] {item} -> {test_file}")
    print(f"[ITEM] work_dir={work_dir}")

    for key, value in params.items():
        if key not in allowed:
            print(f"  [SKIP] {key}={value} (unused by {item})")
            continue
        os.environ[key] = value
        print(f"  [CONFIG] {key}={value}")

    pytest_args = ["-v", "-s", "--tb=short"]
    if importlib.util.find_spec("allure_pytest") is not None:
        pytest_args.append(f"--alluredir={ALLURE_DIR}")
    elif clean_allure:
        shutil.rmtree(os.path.join(work_dir, ALLURE_DIR), ignore_errors=True)

    if clean_allure and importlib.util.find_spec("allure_pytest") is not None:
        pytest_args.append("--clean-alluredir")
    pytest_args.extend([f"--junitxml=report_{item}.xml", test_file])

    previous = os.getcwd()
    try:
        os.chdir(work_dir)
        return int(pytest.main(pytest_args))
    finally:
        os.chdir(previous)


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
        "basic_io": ("basic_io", "test_basic_io"),
        "basic_rebuild_io": ("basic_rebuild_io", "test_basic_rebuild_io"),
        "multi_raid_io": ("multi_raid_io", "test_multi_raid_io"),
        "multi_raid_degraded_io": ("multi_raid_degraded_io", "test_multi_raid_degraded_io"),
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
    executed_items = []
    junit_final = os.path.join(base_dir, JUNIT_FINAL)
    os.makedirs(os.path.join(base_dir, CASES_DIR), exist_ok=True)
    for index, item in enumerate(run_order):
        params = params_map.get(item, {})
        monitor_enabled = stress_monitor_enabled(params)
        print(f"[ITEM_START] {item}")
        exit_code = 2
        case_dir = prepare_case_workdir(base_dir, item)
        print(f"[ITEM] case workspace: {case_dir}")
        try:
            if monitor_enabled:
                clean_monitor_log(case_dir)
            exit_code = run_single_item(item, params, clean_allure=True, work_dir=case_dir)
            print(f"[ITEM_END] {item} exit_code={exit_code}")
        finally:
            if monitor_enabled:
                stop_monitor_for_item(case_dir)
                try:
                    add_allure_monitor_archive(item, case_dir)
                except Exception as exc:
                    print(f"[WARN] Failed to archive monitor log for {item}: {exc}")
            try:
                collect_case_outputs(case_dir, base_dir, item)
            except Exception as exc:
                print(f"[WARN] Failed to collect outputs for {item}: {exc}")
            executed_items.append(item)
            exit_codes.append(exit_code)
            # Merge after every item so idle/external kills still keep completed reports.
            previous = os.getcwd()
            try:
                os.chdir(base_dir)
                merge_junit_reports(executed_items, junit_final)
            finally:
                os.chdir(previous)

        if exit_code != 0:
            print(f"[FAIL_FAST] Stop after {item} failed with exit_code={exit_code}")
            break

    sys.exit(max(exit_codes) if exit_codes else 0)


if __name__ == "__main__":
    main()
