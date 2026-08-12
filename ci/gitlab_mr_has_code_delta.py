#!/usr/bin/env python3
"""Return 0 if GitLab compare JSON has commits or diffs; else 1."""
import json
import sys


def main():
    if len(sys.argv) != 2:
        print("usage: gitlab_mr_has_code_delta.py compare.json", file=sys.stderr)
        return 2
    with open(sys.argv[1], encoding="utf-8") as handle:
        data = json.load(handle)
    commits = data.get("commits") or []
    diffs = data.get("diffs") or []
    if commits or diffs:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
