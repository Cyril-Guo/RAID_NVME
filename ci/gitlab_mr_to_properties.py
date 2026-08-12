#!/usr/bin/env python3
import argparse
from datetime import datetime
import json


def prop_value(value):
    return str(value or "").replace("\n", " ").replace("\r", " ")


def epoch_value(value):
    if not value:
        return 0
    try:
        return int(datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp())
    except ValueError:
        return 0


def emit_mr(mr, prefix="MR"):
    iid = prop_value(mr.get("iid"))
    print(f"{prefix}_IID={iid}")
    print(f"{prefix}_TITLE={prop_value(mr.get('title'))}")
    print(f"{prefix}_SOURCE_BRANCH={prop_value(mr.get('source_branch'))}")
    print(f"{prefix}_TARGET_BRANCH={prop_value(mr.get('target_branch'))}")
    print(f"{prefix}_SHA={prop_value(mr.get('sha'))}")
    print(f"{prefix}_UPDATED_AT={prop_value(mr.get('updated_at'))}")
    print(f"{prefix}_UPDATED_EPOCH={epoch_value(mr.get('updated_at'))}")
    print(f"{prefix}_WEB_URL={prop_value(mr.get('web_url'))}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("json_path")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()

    with open(args.json_path, encoding="utf-8") as fh:
        data = json.load(fh)

    if not args.list:
        emit_mr(data)
        return

    merge_requests = [
        mr for mr in data
        if not str(mr.get("title") or "").strip().lower().startswith("[wip]")
    ]
    if not merge_requests:
        print("MR_COUNT=0")
        print("MR_SIGNATURE=none")
        print("MR_IDS=")
        return

    # Stable signature order by iid; do not use "most recently updated" as the trigger target.
    ordered = sorted(merge_requests, key=lambda item: item.get("iid") or 0)
    signature_parts = [f"{mr.get('iid')}:{mr.get('sha')}" for mr in ordered]
    created_epoch_parts = [
        f"{mr.get('iid')}:{epoch_value(mr.get('created_at'))}" for mr in ordered
    ]
    id_parts = [str(mr.get("iid") or "") for mr in ordered]

    print(f"MR_COUNT={len(ordered)}")
    print(f"MR_SIGNATURE={prop_value('|'.join(signature_parts))}")
    print(f"MR_CREATED_EPOCH_SIGNATURE={prop_value('|'.join(created_epoch_parts))}")
    print(f"MR_IDS={prop_value('|'.join(id_parts))}")
    for mr in ordered:
        iid = mr.get("iid")
        emit_mr(mr, prefix=f"MR_{iid}")


if __name__ == "__main__":
    main()
