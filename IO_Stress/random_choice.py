#!/usr/bin/env python3
"""Dispatch mix model by IO_BS_ALIGN=4k|512 (set by CI case scripts; default 4k)."""
from __future__ import annotations

import os
import runpy
import pathlib

align = os.environ.get("IO_BS_ALIGN", "4k").strip().lower()
if align in ("4k", "4kb", "4096"):
    target = "random_choice_4k.py"
elif align in ("512", "512b", "512B"):
    target = "random_choice_512.py"
else:
    raise SystemExit(f"IO_BS_ALIGN must be 4k or 512, got {align!r}")

path = pathlib.Path(__file__).resolve().parent / target
runpy.run_path(str(path), run_name="__main__")
