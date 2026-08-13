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
CASES_DIR = "cases"

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

SELECTION_BEGIN = "# === BEGIN SELECTION（自动同步；名称后数字为执行顺序，# 表示不跑）==="
SELECTION_END = "# === END SELECTION ==="
_SMOKE_ORDER_RE = re.compile(r"^test_smoke_(\d+)_.+\.py$", re.IGNORECASE)
_SELECTION_ENTRY_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(?:\s+(\d+))?$")


def parse_selection_entry(line):
    """Parse a selection line into (name, order|None, enabled), or None."""
    text = line.strip()
    if not text:
        return None
    enabled = True
    if text.startswith("#"):
        text = text[1:].strip()
        enabled = False
        if not text or text.startswith("="):
            return None
    if text.startswith("[") and text.endswith("]"):
        return None
    if "=" in text:
        return None
    match = _SELECTION_ENTRY_RE.fullmatch(text)
    if not match:
        return None
    name = match.group(1).lower()
    order = int(match.group(2)) if match.group(2) else None
    return name, order, enabled


def _selection_entry_name(line):
    """Return item name from a whitelist line, or None if not an entry."""
    parsed = parse_selection_entry(line)
    return parsed[0] if parsed else None


def catalog_default_order(name, catalog):
    """Prefer smoke file number (test_smoke_03_*.py -> 3); else None."""
    path = catalog.get(name, "")
    match = _SMOKE_ORDER_RE.match(os.path.basename(path))
    if match:
        return int(match.group(1))
    return None


def read_selection_entries(path):
    """Return [(name, order|None, enabled), ...] from the selection block."""
    block_entries = []
    legacy_entries = []
    if not os.path.exists(path):
        return block_entries

    in_block = False
    saw_marker = False
    with open(path, "r", encoding="utf-8") as handle:
        for raw in handle:
            stripped = raw.strip()
            if stripped.startswith("# === BEGIN SELECTION"):
                in_block = True
                saw_marker = True
                continue
            if stripped.startswith("# === END SELECTION"):
                break

            if saw_marker:
                if not in_block or not stripped:
                    continue
                parsed = parse_selection_entry(raw)
                if parsed:
                    block_entries.append(parsed)
                continue

            # Legacy fallback only when no BEGIN/END block exists.
            if stripped.startswith("[") and stripped.endswith("]"):
                break
            if not stripped:
                continue
            parsed = parse_selection_entry(raw)
            if parsed:
                legacy_entries.append(parsed)
    return block_entries if saw_marker else legacy_entries


def read_enabled_selection(path):
    """Enabled item names sorted by order ascending (then name)."""
    enabled = [entry for entry in read_selection_entries(path) if entry[2]]
    enabled.sort(key=lambda entry: (entry[1] if entry[1] is not None else 10**9, entry[0]))
    return [name for name, _order, _enabled in enabled]


def build_synced_selection_order(existing_entries, catalog):
    """Keep known items' order/enable state; assign numbers to new items; sort by order."""
    catalog_names = list(catalog)
    catalog_set = set(catalog_names)
    ordered = []
    seen = set()
    used_orders = set()

    for name, order, enabled in existing_entries:
        if name not in catalog_set or name in seen:
            continue
        if order is None:
            order = catalog_default_order(name, catalog)
        ordered.append((name, order, bool(enabled)))
        seen.add(name)
        if order is not None:
            used_orders.add(order)

    next_order = (max(used_orders) + 1) if used_orders else 1
    for name in catalog_names:
        if name in seen:
            continue
        order = catalog_default_order(name, catalog)
        if order is None or order in used_orders:
            while next_order in used_orders:
                next_order += 1
            order = next_order
            next_order += 1
        ordered.append((name, order, False))
        seen.add(name)
        used_orders.add(order)

    # Fill any still-missing orders stably.
    for idx, (name, order, enabled) in enumerate(ordered):
        if order is not None:
            continue
        while next_order in used_orders:
            next_order += 1
        ordered[idx] = (name, next_order, enabled)
        used_orders.add(next_order)
        next_order += 1

    ordered.sort(key=lambda entry: (entry[1], entry[0]))
    return ordered


def format_selection_line(name, order, enabled):
    body = f"{name} {order}"
    return f"{body}\n" if enabled else f"# {body}\n"


def sync_selection_list(path, catalog):
    """Rewrite selection block so every discovered item is listed for easy toggle.

    Preserve enable/disable and numeric order; sort lines by order ascending.
    Newly discovered names are added as '# name <order>'.
    Returns True when the file content changed.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(path)

    with open(path, "r", encoding="utf-8") as handle:
        original = handle.read()
        lines = original.splitlines(keepends=True)

    begin_idx = end_idx = section_idx = None
    for idx, raw in enumerate(lines):
        stripped = raw.strip()
        if begin_idx is None and stripped.startswith("# === BEGIN SELECTION"):
            begin_idx = idx
            continue
        if begin_idx is not None and end_idx is None and stripped.startswith("# === END SELECTION"):
            end_idx = idx
            break
        if section_idx is None and stripped.startswith("[") and stripped.endswith("]"):
            section_idx = idx
            if begin_idx is None:
                break

    existing_entries = read_selection_entries(path)
    ordered = build_synced_selection_order(existing_entries, catalog)

    selection_lines = [SELECTION_BEGIN + "\n"]
    for name, order, enabled in ordered:
        selection_lines.append(format_selection_line(name, order, enabled))
    selection_lines.append(SELECTION_END + "\n")

    if begin_idx is not None and end_idx is not None and end_idx > begin_idx:
        new_lines = lines[:begin_idx] + selection_lines + lines[end_idx + 1 :]
    elif section_idx is not None:
        # Insert synced block just before the first parameter section.
        # Drop legacy bare/commented item lines immediately above that section.
        insert_at = section_idx
        while insert_at > 0:
            prev = lines[insert_at - 1].strip()
            if not prev:
                insert_at -= 1
                continue
            if _selection_entry_name(lines[insert_at - 1]) is not None:
                insert_at -= 1
                continue
            break
        new_lines = lines[:insert_at] + ["\n"] + selection_lines + ["\n"] + lines[section_idx:]
    else:
        new_lines = lines + ["\n"] + selection_lines

    updated = "".join(new_lines)
    if updated == original:
        return False
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(updated)
    return True


def parse_items_file(path):
    """Parse whitelist + per-item parameter blocks.

    Selection comes from the BEGIN/END SELECTION block: uncommented
    `name <order>` lines, sorted by order. Each [item] block holds params.
    """
    selected = read_enabled_selection(path)
    params_map = {}
    current = None

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
                if current:
                    params_map.setdefault(current, {})
                continue
            if current is None:
                continue
            if "=" not in line:
                continue
            key, value = [part.strip() for part in line.split("=", 1)]
            params_map[current][key] = value

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


def run_single_item(item, params, clean_allure, test_items=None, work_dir=None):
    catalog = test_items if test_items is not None else TEST_ITEMS
    test_file = catalog[item]
    work_dir = work_dir or os.getcwd()

    for key in ALL_PARAM_KEYS:
        os.environ.pop(key, None)

    print("\n" + "=" * 60)
    print(f"[ITEM] {item} -> {test_file}")
    print(f"[ITEM] work_dir={work_dir}")

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
        "basic_io": ("basic_io", "basic_io"),
        "basic_rebuild_io": ("basic_rebuild_io", "basic_rebuild_io"),
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


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    base_dir = os.path.dirname(os.path.abspath(__file__))
    items_path = os.path.join(base_dir, ITEMS_FILE)
    test_items = discover_test_items(os.path.join(base_dir, ITEMS_DIR))

    sync_only = "--sync-selection" in argv
    changed = sync_selection_list(items_path, test_items)
    if changed:
        print(f"[SYNC] Updated selection list in {ITEMS_FILE}: {list(test_items.keys())}")
    else:
        print(f"[SYNC] Selection list already up to date: {list(test_items.keys())}")
    if sync_only:
        return 0

    selected, params_map = parse_items_file(items_path)
    invalid, missing = validate_selection(selected, test_items=test_items, base_dir=base_dir)

    if invalid:
        print(f"[ERROR] Unknown test items: {invalid}")
        print(f"[ERROR] Available items: {list(test_items.keys())}")
        sys.exit(2)

    if missing:
        print(f"[ERROR] Missing test files: {missing}")
        sys.exit(2)

    # selected is already sorted by numeric order from test_items.txt.
    run_order = [item for item in selected if item in test_items]

    if not run_order:
        print(f"[ERROR] No valid test items selected in {ITEMS_FILE}.")
        print(
            f"[ERROR] Uncomment `name <order>` lines inside BEGIN/END SELECTION. "
            f"Available: {list(test_items.keys())}"
        )
        sys.exit(2)

    print(f"Selected test items: {run_order}")
    print(f"Discovered test items: {list(test_items.keys())}")

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
            exit_code = run_single_item(
                item,
                params,
                clean_allure=True,
                test_items=test_items,
                work_dir=case_dir,
            )
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
    if "--sync-selection" in sys.argv[1:]:
        sys.exit(main(sys.argv[1:]))
    main()
