#!/usr/bin/env python3
"""Rewrite test_items.txt git blob as plaintext via hash-object --stdin.

On some Windows hosts a transparent file-encryption agent (TSD) makes
`git add/hash-object <path>` store ciphertext. Feeding bytes on stdin avoids that.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "test_items.txt"


def main() -> int:
    raw = PATH.read_bytes()
    # Normalize to LF; drop UTF-8 BOM if present.
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    text = raw.decode("utf-8")
    payload = text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")
    if payload.startswith(b"%TSD-Header-###%"):
        print("ERROR: worktree read still looks encrypted", file=sys.stderr)
        return 1
    if not payload.lstrip().startswith(b"#"):
        print("ERROR: unexpected test_items.txt content", file=sys.stderr)
        return 1

    sha = subprocess.check_output(
        ["git", "hash-object", "-w", "--stdin"],
        input=payload,
        cwd=ROOT,
    ).decode().strip()
    subprocess.check_call(
        ["git", "update-index", "--cacheinfo", f"100644,{sha},test_items.txt"],
        cwd=ROOT,
    )

    stored = subprocess.check_output(["git", "cat-file", "-p", sha], cwd=ROOT)
    if stored.startswith(b"%TSD-Header-###%"):
        print("ERROR: stored blob is still TSD ciphertext", file=sys.stderr)
        return 1
    if stored != payload:
        print("ERROR: stored blob mismatch", file=sys.stderr)
        return 1
    print(f"OK staged plaintext test_items.txt sha={sha} bytes={len(payload)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
