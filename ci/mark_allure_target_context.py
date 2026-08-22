#!/usr/bin/env python3
import glob
import json
import os
import sys


def display_label(kind):
    return "Physical"


def set_label(labels, name, value):
    labels = [label for label in labels if label.get("name") != name]
    labels.append({"name": name, "value": value})
    return labels


def rename_attachment(allure_dir, attachment, prefix):
    source = attachment.get("source")
    if not source or source.startswith(prefix):
        return

    old_path = os.path.join(allure_dir, source)
    new_source = f"{prefix}{source}"
    new_path = os.path.join(allure_dir, new_source)
    if os.path.exists(old_path):
        if os.path.exists(new_path):
            os.remove(new_path)
        os.rename(old_path, new_path)
    attachment["source"] = new_source


def normalize_result(path, allure_dir, node, kind):
    with open(path, "r", encoding="utf-8") as handle:
        result = json.load(handle)

    prefix_text = f"[{display_label(kind)} {node}] "
    original_name = result.get("name") or "unknown"
    display_name = original_name if original_name.startswith(prefix_text) else f"{prefix_text}{original_name}"
    base_full_name = result.get("fullName") or result.get("historyId") or original_name
    labels = result.get("labels") or []
    label_map = {label.get("name"): label.get("value") for label in labels if label.get("name")}
    run_key = label_map.get("run_key") or label_map.get("package") or ""
    if run_key and run_key not in base_full_name:
        base_full_name = f"{run_key}::{base_full_name}"
    context_key = f"{kind}:{node}:{base_full_name}"

    result["name"] = display_name
    result["fullName"] = context_key
    result["historyId"] = context_key
    result["testCaseId"] = context_key
    labels = result.get("labels") or []
    labels = set_label(labels, "host", node)
    labels = set_label(labels, "target", kind)
    result["labels"] = labels

    attachment_prefix = f"{kind}_{node.replace('.', '_')}_"
    for attachment in result.get("attachments") or []:
        rename_attachment(allure_dir, attachment, attachment_prefix)

    with open(path, "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False)


def normalize_sidecar(path, allure_dir, node, kind):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            pending = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return

    attachment_prefix = f"{kind}_{node.replace('.', '_')}_"
    for entry in pending:
        attachment = entry.get("attachment") or {}
        rename_attachment(allure_dir, attachment, attachment_prefix)
        entry["host"] = node
        entry["target"] = kind

    with open(path, "w", encoding="utf-8") as handle:
        json.dump(pending, handle, ensure_ascii=False)


def main(argv=None):
    argv = argv or sys.argv[1:]
    if len(argv) != 2:
        print("usage: mark_allure_target_context.py <allure_dir> <node_ip>")
        return 2

    allure_dir, node = argv
    kind = "physical"
    if not os.path.isdir(allure_dir):
        return 0

    updated = 0
    for path in glob.glob(os.path.join(allure_dir, "*-result.json")):
        normalize_result(path, allure_dir, node, kind)
        updated += 1

    normalize_sidecar(os.path.join(allure_dir, "monitor_attachments.json"), allure_dir, node, kind)
    print(f"marked allure target context: {updated} result files as {kind} on {node}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
