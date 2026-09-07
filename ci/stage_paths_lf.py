#!/usr/bin/env python3
"""Stage listed paths as UTF-8 LF via hash-object --stdin (avoid TSD path reads)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ci.restage_text_lf import normalize_text, should_normalize, stage_bytes  # noqa: E402


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: stage_paths_lf.py <path>...", file=sys.stderr)
        return 2
    for path in argv:
        raw = (ROOT / path).read_bytes()
        if raw.startswith(b"%TSD-Header-###%"):
            print(f"ERROR worktree encrypted: {path}", file=sys.stderr)
            return 1
        payload = raw if not should_normalize(path) else normalize_text(raw)
        exists = subprocess_path_in_index(path)
        sha = stage_bytes(path, payload, add=not exists)
        print(f"staged {path} sha={sha} bytes={len(payload)}")
    return 0


def subprocess_path_in_index(path: str) -> bool:
    import subprocess

    out = subprocess.check_output(["git", "ls-files", "--", path], cwd=ROOT, text=True)
    return bool(out.strip())


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
