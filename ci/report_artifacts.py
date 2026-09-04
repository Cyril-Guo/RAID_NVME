"""Associate controller-side collection artifacts with their node and run."""
import os
import re
import shutil
from pathlib import Path

try:
    from ci.report_identity import host, read_json, run_key, save_json, set_label
except ModuleNotFoundError:
    from report_identity import host, read_json, run_key, save_json, set_label

BUNDLE_NAME = re.compile(
    r"failure_bundle_(\d+\.\d+\.\d+\.\d+)_(.+)_\d{8}_\d{6}(?:_[A-Za-z0-9]+)*\.tar\.gz\Z")
ITEM_EVENT = re.compile(r"\[ITEM_(START|END)\]\s+([A-Za-z0-9_]+)(?:\s+exit_code=(\d+))?")


def last_run(log):
    """Return the active or last failed case; a completed pass is not a failure."""
    active = ""
    try:
        with log.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                match = ITEM_EVENT.search(line)
                if match:
                    active = match[2] if match[1] == "START" or match[3] != "0" else ""
    except OSError:
        pass
    return active


def _land_file(source, root):
    destination = root / source.name
    if not destination.exists():
        try:
            os.link(source, destination)
        except OSError:
            shutil.copy2(source, destination)
    return destination.name


def attach_workspace_artifacts(allure_dir, workspace="."):
    root, workspace = Path(allure_dir), Path(workspace)
    records = [(p, r) for p in root.glob("*-result.json") if (r := read_json(p))]
    for _, result in records:
        if str(result.get("name", "")).startswith("Test_Execution_") and not run_key(result):
            key = last_run(workspace / f"test_execution_{host(result)}.log")
            if key:
                set_label(result, "run_key", key)
                result["description"] = f"Interrupted test execution; last active or failed run_key={key}."
    attached = 0
    for bundle in workspace.glob("failure_bundle_*.tar.gz"):
        match = BUNDLE_NAME.fullmatch(bundle.name)
        if not match or not bundle.is_file() or bundle.is_symlink():
            continue
        node, key = match[1], match[2]
        if key == "remote_runner":
            key = last_run(workspace / f"test_execution_{node}.log")
        targets = [r for _, r in records if host(r) == node and
                   (run_key(r) == key if key else r.get("status") in ("failed", "broken"))]
        if not targets:
            # Infrastructure fallback has no run key, but still needs the node bundle.
            targets = [r for _, r in records if host(r) == node and not run_key(r)
                       and r.get("status") in ("failed", "broken")]
        if not targets:
            print(f"[ARTIFACT_WARNING] No matching report for {bundle.name}; node={node} run_key={key or 'unknown'}")
            continue
        try:
            source = _land_file(bundle, root)
        except OSError as exc:
            print(f"[ARTIFACT_WARNING] Cannot attach {bundle.name}: {exc}")
            continue
        for result in targets:
            name = f"故障诊断包 {key}" if key else "节点故障诊断包（用例未定位）"
            result.setdefault("attachments", []).append({"name": name, "source": source, "type": "application/gzip"})
            attached += 1

    for path, result in records:
        node = host(result)
        execution = workspace / f"test_execution_{node}.log"
        if node and result.get("status") in ("failed", "broken") and execution.is_file():
            try:
                source = _land_file(execution, root)
                result.setdefault("attachments", []).append({"name": "节点执行及日志回收记录",
                                                              "source": source, "type": "text/plain"})
            except OSError as exc:
                print(f"[ARTIFACT_WARNING] Cannot attach {execution.name}: {exc}")
        save_json(path, result)
    return attached
