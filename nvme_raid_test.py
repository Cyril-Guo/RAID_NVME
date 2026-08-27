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
    "FIO_CONFIG",
    "IGNORE_ERROR",
    "FIO_DISKS",
    "STRESS_MONITOR",
    "MONITOR_RUNTIME",
    "RANDOM_IO_DURATION",
    "MIX_FAIL_ON_ANY",
)
ALL_PARAM_KEYS = sorted(ALLOWED_PARAM_KEYS)

ITEMS_FILE = "test_items.txt"
ITEMS_DIR = "test_items"
ALLURE_DIR = "allure-results"
JUNIT_FINAL = "report.xml"
CASES_DIR = "cases"
RUN_KEY_ENV = "RAID_NVME_RUN_KEY"
RUN_ORDER_ENV = "RAID_NVME_RUN_ORDER"
ITEM_ENV = "RAID_NVME_ITEM"
_NODE_IP_REPORT_RE = re.compile(r"^\d+\.\d+\.\d+\.\d+$")

_CI_NAME_RE = re.compile(r"^test_ci_\d+_(.+)\.py$", re.IGNORECASE)
_TEST_NAME_RE = re.compile(r"^test_(.+)\.py$", re.IGNORECASE)
_SKIP_NAME_RE = re.compile(
    r"(^__init__\.py$|_common\.py$|^powercycle_launch\.py$|^fio_run\.py$|^fio_allure\.py$|^random_io_plan\.py$)",
    re.IGNORECASE,
)


def item_name_from_filename(filename):
    """Map test_ci_03_lawdisk.py -> lawdisk, test_foo.py -> foo."""
    if _SKIP_NAME_RE.search(filename):
        return None
    match = _CI_NAME_RE.match(filename)
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
_CI_ORDER_RE = re.compile(r"^test_ci_(\d+)_.+\.py$", re.IGNORECASE)
_SELECTION_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def parse_selection_entry(line):
    """Parse a selection line into (name, orders, enabled), or None.

    orders is a sorted list of unique positive integers, e.g. ``mix 8 10`` -> [8, 10].
    """
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

    parts = text.split()
    if not parts:
        return None
    name = parts[0].lower()
    if not _SELECTION_NAME_RE.fullmatch(name):
        return None

    orders = []
    for token in parts[1:]:
        if not token.isdigit():
            return None
        orders.append(int(token))
    orders = sorted(set(orders))
    return name, orders, enabled


def _selection_entry_name(line):
    """Return item name from a whitelist line, or None if not an entry."""
    parsed = parse_selection_entry(line)
    return parsed[0] if parsed else None


def catalog_default_order(name, catalog):
    """Prefer CI file number (test_ci_03_*.py -> 3); else None."""
    path = catalog.get(name, "")
    match = _CI_ORDER_RE.match(os.path.basename(path))
    if match:
        return int(match.group(1))
    return None


def _selection_sort_key(orders):
    if orders:
        return (orders[0],)
    return (10**9,)


def read_selection_entries(path):
    """Return [(name, orders, enabled), ...] from the selection block."""
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
    """Enabled item names expanded by order slots, sorted ascending (then name)."""
    return [entry["item"] for entry in build_run_plan(path)]


def build_run_plan(path, test_items=None):
    """Expand enabled selection lines into ordered run slots.

    ``mix 8 10`` contributes two slots (orders 8 and 10). Every slot uses
    ``run_key`` ``{item}__{order}`` for isolated artifacts and reporting.
    """
    catalog = test_items if test_items is not None else TEST_ITEMS
    slots = []
    for name, orders, enabled in read_selection_entries(path):
        if not enabled or name not in catalog:
            continue
        if not orders:
            default_order = catalog_default_order(name, catalog)
            orders = [default_order] if default_order is not None else [10**9]
        for order in orders:
            slots.append((order, name))

    slots.sort(key=lambda entry: (entry[0], entry[1]))

    plan = []
    for order, name in slots:
        run_key = f"{name}__{order}"
        plan.append({"item": name, "order": order, "run_key": run_key})
    return plan


def build_synced_selection_order(existing_entries, catalog):
    """Keep known items' orders/enable state; assign numbers to new items; sort by order."""
    catalog_names = list(catalog)
    catalog_set = set(catalog_names)
    ordered = []
    seen = set()
    used_orders = set()

    for name, orders, enabled in existing_entries:
        if name not in catalog_set or name in seen:
            continue
        if not orders:
            default_order = catalog_default_order(name, catalog)
            orders = [default_order] if default_order is not None else []
        else:
            orders = sorted(set(orders))
        ordered.append((name, orders, bool(enabled)))
        seen.add(name)
        used_orders.update(orders)

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
        ordered.append((name, [order], False))
        seen.add(name)
        used_orders.add(order)

    for idx, (name, orders, enabled) in enumerate(ordered):
        if orders:
            continue
        while next_order in used_orders:
            next_order += 1
        ordered[idx] = (name, [next_order], enabled)
        used_orders.add(next_order)
        next_order += 1

    ordered.sort(key=lambda entry: (_selection_sort_key(entry[1]), entry[0]))
    return ordered


def format_selection_line(name, orders, enabled):
    clean_orders = sorted(set(orders))
    if clean_orders:
        body = f"{name} " + " ".join(str(order) for order in clean_orders)
    else:
        body = name
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
    ``name <order> [<order> ...]`` lines, expanded and sorted by order.
    Each [item] block holds params.
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


def discover_junit_run_keys(directory="."):
    """Return sorted stems for ``report_<run_key>.xml`` (excludes per-node IP reports)."""
    found = []
    pattern = os.path.join(directory, "report_*.xml")
    for path in sorted(glob.glob(pattern)):
        stem = os.path.basename(path)[len("report_") : -len(".xml")]
        if _NODE_IP_REPORT_RE.fullmatch(stem):
            continue
        found.append(stem)
    return found


def collect_failure_bundle(base_dir, run_key, reason="item_failure"):
    """Best-effort gcore + diagnostic tar on the DUT; never raises.

    Returns absolute path to the created archive when available.
    """
    script = os.path.join(base_dir, "ci", "collect_failure_bundle.sh")
    if not os.path.isfile(script):
        print(f"[WARN] Missing failure bundle script: {script}")
        return None
    env = os.environ.copy()
    env["REMOTE_DIR"] = base_dir
    env["NODE_IP"] = env.get("NODE_IP") or env.get("TARGET_IP") or "local"
    env["RUN_KEY"] = str(run_key)
    env["BUNDLE_REASON"] = str(reason)
    try:
        print(f"[FAILURE_BUNDLE] collecting gcore/diagnostics for {run_key}")
        subprocess.run(
            ["bash", script],
            cwd=base_dir,
            env=env,
            check=False,
        )
    except Exception as exc:
        print(f"[WARN] Failure bundle collection failed for {run_key}: {exc}")
        return None

    return _read_latest_bundle_path(base_dir)


def _safe_bundle_token(value):
    text = str(value or "unknown")
    return re.sub(r"[^A-Za-z0-9._-]", "_", text)


def _read_path_file(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            value = handle.read().strip()
        if value and os.path.isfile(value):
            return value
    except OSError:
        pass
    return None


def _read_latest_bundle_path(base_dir):
    bundle_root = os.path.join(base_dir, "failure_bundles")
    latest = _read_path_file(os.path.join(bundle_root, "latest_bundle_path.txt"))
    if latest:
        return latest
    matches = sorted(
        glob.glob(os.path.join(bundle_root, "failure_bundle_*.tar.gz")),
        key=os.path.getmtime,
        reverse=True,
    )
    return matches[0] if matches else None


def find_live_failure_bundle(base_dir, run_key, wait_seconds=120):
    """Return archive from an in-FIO EIO live collect for this run_key, if any.

    Waits briefly for a background live collect that is still pending.
    """
    bundle_root = os.path.join(base_dir, "failure_bundles")
    safe_key = _safe_bundle_token(run_key)
    live_path_file = os.path.join(bundle_root, f"live_bundle_{safe_key}.txt")
    pending_file = os.path.join(bundle_root, f"live_collect_pending_{safe_key}.txt")
    preferred_file = os.path.join(bundle_root, "preferred_live_bundle_path.txt")

    deadline = time.time() + max(0, int(wait_seconds))
    while True:
        live = _read_path_file(live_path_file)
        if live:
            return live
        preferred = _read_path_file(preferred_file)
        if preferred and f"_{safe_key}_" in os.path.basename(preferred):
            return preferred
        if not os.path.isfile(pending_file):
            break
        if time.time() >= deadline:
            print(
                f"[FAILURE_BUNDLE] timed out waiting for live collect "
                f"({pending_file})"
            )
            break
        time.sleep(2)

    return _read_path_file(live_path_file)


def resolve_failure_bundle_for_item(base_dir, run_key, exit_code):
    """Prefer live EIO bundle; only re-collect when no live archive exists."""
    live = find_live_failure_bundle(base_dir, run_key)
    if live:
        print(
            f"[FAILURE_BUNDLE] preferring live EIO bundle for {run_key}: "
            f"{os.path.basename(live)} (skip item_failure re-collect)"
        )
        return live
    return collect_failure_bundle(
        base_dir, run_key, reason=f"item_failure:{exit_code}"
    )


def enable_failure_coredumps(base_dir):
    """Best-effort ulimit/core_pattern setup before the run plan."""
    script = os.path.join(base_dir, "ci", "enable_failure_coredumps.sh")
    if not os.path.isfile(script):
        return
    env = os.environ.copy()
    env["REMOTE_DIR"] = base_dir
    env.setdefault("NODE_IP", env.get("TARGET_IP") or "local")
    try:
        subprocess.run(["bash", script], cwd=base_dir, env=env, check=False)
    except Exception as exc:
        print(f"[WARN] enable_failure_coredumps failed: {exc}")


def enable_draid_pending_debug(base_dir):
    """Best-effort RAID1 pending debug knobs before the run plan."""
    script = os.path.join(base_dir, "ci", "enable_draid_pending_debug.sh")
    if not os.path.isfile(script):
        return
    env = os.environ.copy()
    env["REMOTE_DIR"] = base_dir
    env.setdefault("NODE_IP", env.get("TARGET_IP") or "local")
    try:
        print("[DRAID_DEBUG] enabling RAID1 pending debug knobs (best-effort)")
        subprocess.run(["bash", script], cwd=base_dir, env=env, check=False)
    except Exception as exc:
        print(f"[WARN] enable_draid_pending_debug failed: {exc}")


def add_allure_failure_bundle(run_key, base_dir, item=None, archive_path=None):
    """Copy failure bundle into allure-results and attach to the matching case."""
    item = item or run_key.split("__", 1)[0]
    bundle_root = os.path.join(base_dir, "failure_bundles")
    if not archive_path or not os.path.isfile(archive_path):
        # Prefer live EIO capture over whatever latest_bundle_path points to.
        archive_path = find_live_failure_bundle(base_dir, run_key, wait_seconds=0)
    if not archive_path or not os.path.isfile(archive_path):
        archive_path = _read_path_file(
            os.path.join(bundle_root, "latest_bundle_path.txt")
        )
    if not archive_path or not os.path.isfile(archive_path):
        matches = sorted(
            glob.glob(os.path.join(bundle_root, "failure_bundle_*.tar.gz")),
            key=os.path.getmtime,
            reverse=True,
        )
        archive_path = matches[0] if matches else None
    if not archive_path:
        print(f"[WARN] No failure_bundle archive to attach for {run_key}")
        return

    allure_dir = os.path.join(base_dir, ALLURE_DIR)
    os.makedirs(allure_dir, exist_ok=True)

    archive_name = "failure_bundle_{}.tar.gz".format(run_key)
    dest_archive = os.path.join(allure_dir, archive_name)
    shutil.copy2(archive_path, dest_archive)

    # Also land a copy at workspace root for Jenkins archiveArtifacts / SCP.
    root_copy = os.path.join(base_dir, archive_name)
    try:
        shutil.copy2(archive_path, root_copy)
    except OSError as exc:
        print(f"[WARN] Failed to copy failure bundle to workspace root: {exc}")

    summary_src = os.path.join(bundle_root, "latest_bundle_summary.txt")
    summary_name = "failure_gcore_summary_{}.txt".format(run_key)
    dest_summary = os.path.join(allure_dir, summary_name)
    if os.path.isfile(summary_src):
        shutil.copy2(summary_src, dest_summary)
    else:
        with open(dest_summary, "w", encoding="utf-8") as handle:
            handle.write(
                "failure bundle: {}\n"
                "NOTE: summary missing; unpack the tar.gz for cores/gcore_errors.txt\n".format(
                    archive_name
                )
            )

    attached_tar = _attach_named_file_to_allure(
        item,
        base_dir,
        archive_name,
        display_name="failure_gcore_bundle_{}".format(run_key),
        mime="application/gzip",
        run_key=run_key,
    )
    _attach_named_file_to_allure(
        item,
        base_dir,
        summary_name,
        display_name="failure_gcore_summary_{}".format(run_key),
        mime="text/plain",
        run_key=run_key,
    )
    if attached_tar:
        print(f"[FAILURE_BUNDLE] attached to Allure for {run_key}")
    else:
        print(f"[FAILURE_BUNDLE] queued Allure attachment for {run_key}")


def _attach_named_file_to_allure(item, base_dir, source_name, display_name, mime, run_key=None):
    allure_dir = os.path.join(base_dir, ALLURE_DIR)
    attachment = {
        "name": display_name,
        "source": source_name,
        "type": mime,
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
        if not result_matches_item(result, item, run_key=run_key):
            continue
        attachments = result.setdefault("attachments", [])
        updated = False
        for existing in attachments:
            if existing.get("source") == source_name:
                existing["name"] = display_name
                existing["type"] = mime
                updated = True
                break
        if not updated:
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
    pending.append({"item": item, "attachment": attachment, "run_key": run_key})
    with open(sidecar, "w", encoding="utf-8") as handle:
        json.dump(pending, handle, ensure_ascii=False)
    return False


def collect_case_outputs(case_dir, repo_root, run_key):
    """Copy per-case junit/allure artifacts back to the build root for Jenkins collect."""
    src_report = os.path.join(case_dir, f"report_{run_key}.xml")
    dst_report = os.path.join(repo_root, f"report_{run_key}.xml")
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


def run_single_item(
    item,
    params,
    clean_allure,
    test_items=None,
    work_dir=None,
    run_key=None,
    order=None,
):
    catalog = test_items if test_items is not None else TEST_ITEMS
    test_file = catalog[item]
    work_dir = work_dir or os.getcwd()
    run_key = run_key or item

    for key in ALL_PARAM_KEYS:
        os.environ.pop(key, None)

    print("\n" + "=" * 60)
    print(f"[ITEM] {item} -> {test_file}")
    if run_key != item:
        print(f"[ITEM] run_key={run_key}")
    print(f"[ITEM] work_dir={work_dir}")

    for key, value in params.items():
        if key not in ALLOWED_PARAM_KEYS:
            print(f"  [SKIP] {key}={value} (unused by {item})")
            continue
        os.environ[key] = value
        print(f"  [CONFIG] {key}={value}")

    # Every case except env_prepare:
    # rmmod -> insmod -> force clear all accel -> rmmod -> insmod.
    if item != "env_prepare":
        previous_clear = os.getcwd()
        try:
            os.chdir(work_dir)
            from test_items.basic_io_common import CommandLog, release_and_clear_csd

            print(f"[ITEM] per-case CSD refresh before {item}")
            release_and_clear_csd([], CommandLog())
        finally:
            os.chdir(previous_clear)

    pytest_args = ["-v", "-s", "--tb=short"]
    if importlib.util.find_spec("allure_pytest") is not None:
        pytest_args.append(f"--alluredir={ALLURE_DIR}")
    elif clean_allure:
        shutil.rmtree(os.path.join(work_dir, ALLURE_DIR), ignore_errors=True)

    if clean_allure and importlib.util.find_spec("allure_pytest") is not None:
        pytest_args.append("--clean-alluredir")
    pytest_args.extend([f"--junitxml=report_{run_key}.xml", test_file])

    previous = os.getcwd()
    previous_case_root = os.environ.get("RAID_NVME_CASE_ROOT")
    previous_run_context = {
        RUN_KEY_ENV: os.environ.get(RUN_KEY_ENV),
        RUN_ORDER_ENV: os.environ.get(RUN_ORDER_ENV),
        ITEM_ENV: os.environ.get(ITEM_ENV),
    }
    try:
        os.chdir(work_dir)
        # Smoke tests must not resolve IO_Stress via dirname(__file__): test_items is
        # symlinked into cases/<item>/, so __file__ points at the shared tree.
        os.environ["RAID_NVME_CASE_ROOT"] = os.path.abspath(work_dir)
        os.environ[RUN_KEY_ENV] = run_key
        os.environ[ITEM_ENV] = item
        if order is not None:
            os.environ[RUN_ORDER_ENV] = str(order)
        else:
            os.environ.pop(RUN_ORDER_ENV, None)
        return int(pytest.main(pytest_args))
    finally:
        os.chdir(previous)
        if previous_case_root is None:
            os.environ.pop("RAID_NVME_CASE_ROOT", None)
        else:
            os.environ["RAID_NVME_CASE_ROOT"] = previous_case_root
        for key, value in previous_run_context.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


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


def _result_label_map(result):
    return {
        label.get("name"): label.get("value")
        for label in result.get("labels") or []
        if label.get("name")
    }


def result_matches_item(result, item, run_key=None):
    if run_key:
        labels = _result_label_map(result)
        labeled = labels.get("run_key") or labels.get("package") or labels.get("suite")
        if labeled and labeled != run_key:
            return False
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
        "random_io": ("random_io", "randomio"),
    }
    return any(alias in text for alias in aliases.get(item, (item,)))


def attach_monitor_archive_to_result(item, base_dir, archive_name, run_key=None):
    allure_dir = os.path.join(base_dir, ALLURE_DIR)
    label = run_key or item
    attachment = {
        "name": "monitor_log_{}".format(label),
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
        if not result_matches_item(result, item, run_key=run_key):
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


def add_allure_monitor_archive(run_key, base_dir, item=None):
    item = item or run_key.split("__", 1)[0]
    _, monitor_log = monitor_paths(base_dir)
    if not os.path.isdir(monitor_log):
        return

    allure_dir = os.path.join(base_dir, ALLURE_DIR)
    os.makedirs(allure_dir, exist_ok=True)

    archive_name = "monitor_log_{}.tar.gz".format(run_key)
    base_name = os.path.join(allure_dir, "monitor_log_{}".format(run_key))
    shutil.make_archive(base_name, "gztar", root_dir=os.path.dirname(monitor_log), base_dir=os.path.basename(monitor_log))
    attach_monitor_archive_to_result(item, base_dir, archive_name, run_key=run_key)


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

    # Run plan is sorted by numeric order from test_items.txt (items may repeat).
    run_plan = build_run_plan(items_path, test_items=test_items)

    if not run_plan:
        print(f"[ERROR] No valid test items selected in {ITEMS_FILE}.")
        print(
            f"[ERROR] Uncomment `name <order> [<order> ...]` lines inside BEGIN/END SELECTION. "
            f"Available: {list(test_items.keys())}"
        )
        sys.exit(2)

    run_order = [entry["item"] for entry in run_plan]
    print(f"Selected test items: {run_order}")
    print(f"Discovered test items: {list(test_items.keys())}")

    enable_failure_coredumps(base_dir)
    enable_draid_pending_debug(base_dir)

    exit_codes = []
    executed_run_keys = []
    junit_final = os.path.join(base_dir, JUNIT_FINAL)
    os.makedirs(os.path.join(base_dir, CASES_DIR), exist_ok=True)
    for entry in run_plan:
        item = entry["item"]
        run_key = entry["run_key"]
        order = entry["order"]
        params = params_map.get(item, {})
        monitor_enabled = stress_monitor_enabled(params)
        print(f"[ITEM_START] {run_key}")
        if run_key != item:
            print(f"[ITEM] order={order}")
        exit_code = 2
        case_dir = prepare_case_workdir(base_dir, run_key)
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
                run_key=run_key,
                order=order,
            )
            print(f"[ITEM_END] {run_key} exit_code={exit_code}")
        finally:
            if monitor_enabled:
                stop_monitor_for_item(case_dir)
                try:
                    add_allure_monitor_archive(run_key, case_dir, item=item)
                except Exception as exc:
                    print(f"[WARN] Failed to archive monitor log for {run_key}: {exc}")
            try:
                collect_case_outputs(case_dir, base_dir, run_key)
            except Exception as exc:
                print(f"[WARN] Failed to collect outputs for {item}: {exc}")
            if exit_code != 0:
                # Prefer live EIO bundle captured while fio was still running.
                archive = resolve_failure_bundle_for_item(
                    base_dir, run_key, exit_code
                )
                try:
                    add_allure_failure_bundle(
                        run_key, base_dir, item=item, archive_path=archive
                    )
                except Exception as exc:
                    print(f"[WARN] Failed to attach failure bundle to Allure for {run_key}: {exc}")
            executed_run_keys.append(run_key)
            exit_codes.append(exit_code)
            # Merge after every item so idle/external kills still keep completed reports.
            previous = os.getcwd()
            try:
                os.chdir(base_dir)
                merge_junit_reports(executed_run_keys, junit_final)
            finally:
                os.chdir(previous)

        if exit_code != 0:
            print(f"[FAIL_FAST] Stop after {run_key} failed with exit_code={exit_code}")
            break

    sys.exit(max(exit_codes) if exit_codes else 0)


if __name__ == "__main__":
    if "--sync-selection" in sys.argv[1:]:
        sys.exit(main(sys.argv[1:]))
    main()
