#!/usr/bin/env python3
import argparse
import json


def prop_value(value):
    return str(value or "").replace("\n", " ").replace("\r", " ")


def emit_mr(mr):
    print(f"MR_IID={prop_value(mr.get('iid'))}")
    print(f"MR_TITLE={prop_value(mr.get('title'))}")
    print(f"MR_SOURCE_BRANCH={prop_value(mr.get('source_branch'))}")
    print(f"MR_TARGET_BRANCH={prop_value(mr.get('target_branch'))}")
    print(f"MR_SHA={prop_value(mr.get('sha'))}")
    print(f"MR_UPDATED_AT={prop_value(mr.get('updated_at'))}")
    print(f"MR_WEB_URL={prop_value(mr.get('web_url'))}")


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
        return

    signature_parts = [
        f"{mr.get('iid')}:{mr.get('sha')}"
        for mr in sorted(merge_requests, key=lambda item: item.get("iid") or 0)
    ]
    latest = merge_requests[0]
    print(f"MR_COUNT={len(merge_requests)}")
    print(f"MR_SIGNATURE={prop_value('|'.join(signature_parts))}")
    emit_mr(latest)


if __name__ == "__main__":
    main()
