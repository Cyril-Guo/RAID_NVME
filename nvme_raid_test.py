import os
import re
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent
ITEMS_TXT = ROOT / "test_items.txt"
ITEMS_DIR = ROOT / "test_items"


def _parse_selection(path: Path) -> list[tuple[str, int]]:
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    m = re.search(
        r"# === BEGIN SELECTION.*?===\n(.*?)# === END SELECTION",
        text,
        flags=re.S,
    )
    body = m.group(1) if m else text
    selected: list[tuple[str, int]] = []
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        name, seq = parts[0], parts[1]
        if not name.startswith("test_cli_"):
            continue
        try:
            selected.append((name, int(seq)))
        except ValueError:
            continue
    selected.sort(key=lambda x: x[1])
    return selected


def _nodeid_for(case_name: str) -> str | None:
    # test_cli_01_foo -> test_items/test_cli_01_foo.py::test_cli_01_foo
    py = ITEMS_DIR / f"{case_name}.py"
    if not py.is_file():
        return None
    return f"test_items/{case_name}.py::{case_name}"


def main() -> int:
    selected = _parse_selection(ITEMS_TXT)
    if not selected:
        print("[CLI] no cases selected in test_items.txt", flush=True)
        return 0

    nodeids: list[str] = []
    missing: list[str] = []
    for name, _seq in selected:
        nid = _nodeid_for(name)
        if nid is None:
            missing.append(name)
        else:
            nodeids.append(nid)

    if missing:
        print("[CLI] missing case files:", ", ".join(missing), flush=True)
        return 2
    if not nodeids:
        print("[CLI] nothing to run", flush=True)
        return 0

    junit = os.environ.get("CLI_JUNIT_XML", str(ROOT / "reports" / "junit.xml"))
    Path(junit).parent.mkdir(parents=True, exist_ok=True)
    args = [
        "-vv",
        "-s",
        "--tb=short",
        f"--junitxml={junit}",
        *nodeids,
    ]
    print("[CLI] pytest", " ".join(args), flush=True)
    # Sequential, one process: preserve step-by-step console output.
    return int(pytest.main(args))


if __name__ == "__main__":
    sys.exit(main())
