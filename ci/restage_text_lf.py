#!/usr/bin/env python3
"""Restage tracked text blobs as UTF-8 LF via git hash-object --stdin.

Fixes two Windows pitfalls that break Linux Jenkins:
  1) TSD ciphertext stored by path-based git add
  2) CRLF line endings that make `set -o pipefail` fail as `pipefail\\r`

Usage:
  python3 ci/restage_text_lf.py              # restage TSD and/or CRLF blobs
  python3 ci/restage_text_lf.py --crlf-only  # only CRLF
  python3 ci/restage_text_lf.py --tsd-only   # only TSD
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".ko",
    ".bin",
    ".gz",
    ".zip",
    ".xz",
    ".7z",
    ".whl",
    ".so",
    ".dll",
    ".exe",
    ".pyc",
}


def tracked_files() -> list[str]:
    out = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
    return [p.decode("utf-8", "surrogateescape") for p in out.split(b"\0") if p]


def blob_bytes(path: str, rev: str = "HEAD") -> bytes:
    return subprocess.check_output(["git", "cat-file", "-p", f"{rev}:{path}"], cwd=ROOT)


def mode_for(path: str) -> str:
    try:
        out = subprocess.check_output(
            ["git", "ls-files", "-s", "-z", "--", path],
            cwd=ROOT,
        )
        if out:
            # mode sha stage\0path\0
            head = out.split(b"\0", 1)[0].decode("utf-8", "replace")
            return head.split()[0]
    except subprocess.CalledProcessError:
        pass
    return "100644"


def normalize_text(raw: bytes) -> bytes:
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    text = raw.decode("utf-8")
    # Real CR/LF bytes — never rely on shell-escaped \\r\\n strings.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.encode("utf-8")


def should_normalize(path: str) -> bool:
    lower = path.lower()
    return not any(lower.endswith(suf) for suf in SKIP_SUFFIXES)


def stage_bytes(path: str, payload: bytes, add: bool = False) -> str:
    sha = subprocess.check_output(
        ["git", "hash-object", "-w", "--stdin"],
        input=payload,
        cwd=ROOT,
    ).decode().strip()
    mode = mode_for(path)
    cmd = ["git", "update-index"]
    if add:
        cmd.append("--add")
    cmd += ["--cacheinfo", f"{mode},{sha},{path}"]
    subprocess.check_call(cmd, cwd=ROOT)
    stored = subprocess.check_output(["git", "cat-file", "-p", sha], cwd=ROOT)
    if stored.startswith(b"%TSD-Header-###%"):
        raise RuntimeError(f"stored blob still TSD encrypted: {path}")
    if b"\r" in stored and should_normalize(path):
        raise RuntimeError(f"stored blob still contains CR: {path}")
    if stored != payload:
        raise RuntimeError(f"stored blob mismatch: {path}")
    return sha


def restage_path(path: str) -> str:
    work = ROOT / path
    if not work.is_file():
        raise FileNotFoundError(f"missing worktree file: {path}")
    raw = work.read_bytes()
    if raw.startswith(b"%TSD-Header-###%"):
        raise RuntimeError(f"worktree still encrypted: {path}")
    payload = raw if not should_normalize(path) else normalize_text(raw)
    return stage_bytes(path, payload)


def needs_restage(blob: bytes, path: str, crlf_only: bool, tsd_only: bool) -> bool:
    is_tsd = blob.startswith(b"%TSD-Header-###%")
    is_crlf = should_normalize(path) and (b"\r\n" in blob or (b"\r" in blob and not is_tsd))
    if tsd_only:
        return is_tsd
    if crlf_only:
        return is_crlf and not is_tsd
    return is_tsd or is_crlf


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--crlf-only", action="store_true")
    parser.add_argument("--tsd-only", action="store_true")
    args = parser.parse_args()
    if args.crlf_only and args.tsd_only:
        print("ERROR: choose at most one of --crlf-only / --tsd-only", file=sys.stderr)
        return 2

    targets: list[str] = []
    for path in tracked_files():
        try:
            blob = blob_bytes(path)
        except subprocess.CalledProcessError:
            continue
        if needs_restage(blob, path, args.crlf_only, args.tsd_only):
            targets.append(path)

    if not targets:
        print("OK no matching blobs need restage")
        return 0

    print(f"Restaging {len(targets)} blob(s)…")
    failed = 0
    for path in targets:
        try:
            sha = restage_path(path)
        except Exception as exc:  # noqa: BLE001 - report and continue
            print(f"ERROR {path}: {exc}", file=sys.stderr)
            failed += 1
            continue
        print(f"OK {path} sha={sha}")

    if failed:
        print(f"ERROR failed={failed}", file=sys.stderr)
        return 1
    print(f"OK restaged {len(targets)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
