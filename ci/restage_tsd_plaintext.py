#!/usr/bin/env python3
"""Restage all TSD-encrypted git blobs as plaintext via hash-object --stdin.

Windows Transparent Storage Encryption (TSD) can make `git add <path>` store
ciphertext while the worktree still shows plaintext. Feeding bytes on stdin
avoids that path.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".ko", ".bin", ".gz", ".zip", ".xz", ".7z"}


def tracked_files() -> list[str]:
    out = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True)
    return [line.strip() for line in out.splitlines() if line.strip()]


def blob_bytes(path: str) -> bytes:
    return subprocess.check_output(["git", "cat-file", "-p", f"HEAD:{path}"], cwd=ROOT)


def mode_for(path: str) -> str:
    try:
        out = subprocess.check_output(
            ["git", "ls-files", "-s", "--", path],
            cwd=ROOT,
            text=True,
        ).strip()
        if out:
            return out.split()[0]
    except subprocess.CalledProcessError:
        pass
    return "100644"


def restage(path: str) -> str | None:
    work = ROOT / path
    if not work.is_file():
        print(f"SKIP missing worktree: {path}", file=sys.stderr)
        return None
    raw = work.read_bytes()
    if raw.startswith(b"%TSD-Header-###%"):
        print(f"ERROR worktree still encrypted: {path}", file=sys.stderr)
        return None
    # Normalize text-ish files to LF UTF-8 without BOM.
    if path.endswith(tuple(SKIP_SUFFIXES)):
        payload = raw
    else:
        if raw.startswith(b"\xef\xbb\xbf"):
            raw = raw[3:]
        try:
            text = raw.decode("utf-8")
            payload = text.replace("\n", "\n").replace("\n", "\n").encode("utf-8")
        except UnicodeDecodeError:
            payload = raw

    sha = subprocess.check_output(
        ["git", "hash-object", "-w", "--stdin"],
        input=payload,
        cwd=ROOT,
    ).decode().strip()
    mode = mode_for(path)
    subprocess.check_call(
        ["git", "update-index", "--cacheinfo", f"{mode},{sha},{path}"],
        cwd=ROOT,
    )
    stored = subprocess.check_output(["git", "cat-file", "-p", sha], cwd=ROOT)
    if stored.startswith(b"%TSD-Header-###%"):
        print(f"ERROR stored still encrypted: {path}", file=sys.stderr)
        return None
    if stored != payload:
        print(f"ERROR blob mismatch: {path}", file=sys.stderr)
        return None
    return sha


def main() -> int:
    encrypted = []
    for path in tracked_files():
        try:
            blob = blob_bytes(path)
        except subprocess.CalledProcessError:
            continue
        if blob.startswith(b"%TSD-Header-###%"):
            encrypted.append(path)

    if not encrypted:
        print("OK no TSD-encrypted blobs in HEAD")
        return 0

    print(f"Found {len(encrypted)} TSD-encrypted blobs; restaging from worktree…")
    failed = 0
    for path in encrypted:
        sha = restage(path)
        if sha is None:
            failed += 1
            continue
        print(f"OK {path} sha={sha}")

    if failed:
        print(f"ERROR failed={failed}", file=sys.stderr)
        return 1
    print(f"OK restaged {len(encrypted)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
