#!/usr/bin/env python3
"""Legacy entrypoint. Prefer MIX_RANDOM_CHOICE=random_choice_4k.py|random_choice_512.py.

Kept for manual runs: still honors IO_BS_ALIGN=4k|512 if set.
"""
from __future__ import annotations

import os
import runpy
import pathlib

align = os.environ.get("IO_BS_ALIGN", "4k").strip().lower()
explicit = os.environ.get("MIX_RANDOM_CHOICE", "").strip()
if explicit:
    target = pathlib.Path(explicit).name
elif align in ("4k", "4kb", "4096"):
    target = "random_choice_4k.py"
elif align in ("512", "512b", "512B"):
    target = "random_choice_512.py"
else:
    raise SystemExit(
        f"Set MIX_RANDOM_CHOICE to random_choice_4k.py|random_choice_512.py "
        f"(or legacy IO_BS_ALIGN=4k|512); got align={align!r}"
    )

path = pathlib.Path(__file__).resolve().parent / target
runpy.run_path(str(path), run_name="__main__")
