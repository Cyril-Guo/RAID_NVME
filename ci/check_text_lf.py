#!/usr/bin/env python3
"""Fail if tracked text scripts/configs contain CR (CRLF) in the git index/HEAD.

Linux bash treats `set -o pipefail\\r` as an invalid option. Keep text LF-only.

This script must not rely on worktree file contents for ROOT or for the blobs
it checks: Windows TSD can encrypt paths under the repo while git objects stay
plaintext LF.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def repo_root() -> Path:
    out = subprocess.check_output(
        ["git", "rev-parse", "--show-toplevel"],
        stderr=subprocess.DEVNULL,
    )
    return Path(out.decode("utf-8", "surrogateescape").strip())


ROOT = repo_root()
CHECK_SUFFIXES = {
    ".sh",
    ".bash",
    ".py",
    ".pyi",
    ".txt",
    ".md",
    ".csv",
    ".yml",
    ".yaml",
    ".json",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
    ".groovy",
    ".Jenkinsfile",
}
CHECK_NAMES = {
    "Jenkinsfile",
    "Dockerfile",
    "Makefile",
    ".gitattributes",
    ".gitignore",
}


def tracked_files() -> list[str]:
    out = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
    return [p.decode("utf-8", "surrogateescape") for p in out.split(b"\0") if p]


def should_check(path: str) -> bool:
    name = Path(path).name
    if name in CHECK_NAMES:
        return True
    lower = path.lower()
    return any(lower.endswith(suf) for suf in CHECK_SUFFIXES)


def blob_from_index_or_head(path: str) -> bytes | None:
    # Prefer staged index content; fall back to HEAD.
    try:
        return subprocess.check_output(["git", "cat-file", "-p", f":{path}"], cwd=ROOT)
    except subprocess.CalledProcessError:
        pass
    try:
        return subprocess.check_output(["git", "cat-file", "-p", f"HEAD:{path}"], cwd=ROOT)
    except subprocess.CalledProcessError:
        return None


def main() -> int:
    bad: list[str] = []
    for path in tracked_files():
        if not should_check(path):
            continue
        blob = blob_from_index_or_head(path)
        if blob is None:
            continue
        if blob.startswith(b"%TSD-Header-###%"):
            bad.append(f"{path}: TSD ciphertext")
            continue
        if b"\r" in blob:
            bad.append(f"{path}: contains CR/CRLF")

    if bad:
        print("ERROR: tracked text must be LF (no CR) / plaintext:", file=sys.stderr)
        for item in bad:
            print(f"  - {item}", file=sys.stderr)
        print(
            "Fix: python3 ci/restage_text_lf.py && git commit",
            file=sys.stderr,
        )
        return 1

    print("OK: no CR/TSD in checked text blobs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
