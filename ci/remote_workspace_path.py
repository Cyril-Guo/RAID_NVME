#!/usr/bin/env python3
"""Build DUT workspace paths: /root/Cyril/Jenkins/<job>/<branch>/<kind>-<build>."""

from __future__ import annotations

import argparse
import os
import re


def sanitize_segment(value: str, default: str = "unknown") -> str:
    text = (value or "").strip()
    text = re.sub(r"^origin/", "", text)
    text = re.sub(r"[^A-Za-z0-9._-]", "_", text)
    return text or default


def remote_workspace_root(
    job_name: str | None = None,
    branch: str | None = None,
    build_number: str | None = None,
    kind: str = "build",
    base: str = "/root/Cyril/Jenkins",
) -> str:
    job = sanitize_segment(
        job_name
        or os.environ.get("JOB_BASE_NAME")
        or os.environ.get("JOB_NAME")
        or "job"
    )
    branch_name = sanitize_segment(
        branch or os.environ.get("BRANCH_NAME") or os.environ.get("GIT_BRANCH") or "unknown"
    )
    build = sanitize_segment(
        build_number or os.environ.get("BUILD_NUMBER") or "0",
        default="0",
    )
    if kind == "restore":
        prefix = "restore"
    elif kind == "physical":
        prefix = "physical"
    else:
        prefix = "build"
    return f"{base.rstrip('/')}/{job}/{branch_name}/{prefix}-{build}"


def case_workdir(build_root: str, item: str) -> str:
    return "/".join(
        [
            build_root.rstrip("/\\"),
            "cases",
            sanitize_segment(item),
        ]
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=("build", "restore", "physical"), default="build")
    parser.add_argument("--job")
    parser.add_argument("--branch")
    parser.add_argument("--build-number")
    parser.add_argument("--case")
    args = parser.parse_args(argv)
    root = remote_workspace_root(
        job_name=args.job,
        branch=args.branch,
        build_number=args.build_number,
        kind=args.kind,
    )
    if args.case:
        print(case_workdir(root, args.case))
    else:
        print(root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
