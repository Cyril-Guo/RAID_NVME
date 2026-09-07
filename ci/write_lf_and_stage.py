#!/usr/bin/env python3
"""Force LF on a worktree path, then stage via stdin."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ci.restage_text_lf import normalize_text, stage_bytes  # noqa: E402


def main(argv: list[str]) -> int:
    for rel in argv:
        path = ROOT / rel
        payload = normalize_text(path.read_bytes())
        path.write_bytes(payload)
        sha = stage_bytes(rel, payload, add=True)
        print(f"lf+staged {rel} sha={sha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
