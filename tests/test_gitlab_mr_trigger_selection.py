import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def run_py(script, *args):
    return subprocess.run(
        [sys.executable, str(ROOT / script), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_gitlab_mr_list_emits_per_iid_not_latest_only(tmp_path):
    payload = tmp_path / "mrs.json"
    payload.write_text(
        json.dumps(
            [
                {
                    "iid": 12,
                    "title": "newer touch",
                    "source_branch": "feature-b",
                    "target_branch": "main",
                    "sha": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                    "created_at": "2026-01-02T00:00:00Z",
                    "updated_at": "2026-08-12T10:00:00Z",
                    "web_url": "http://example/12",
                },
                {
                    "iid": 7,
                    "title": "older",
                    "source_branch": "feature-a",
                    "target_branch": "main",
                    "sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    "created_at": "2026-01-01T00:00:00Z",
                    "updated_at": "2026-08-01T00:00:00Z",
                    "web_url": "http://example/7",
                },
            ]
        ),
        encoding="utf-8",
    )
    result = run_py("ci/gitlab_mr_to_properties.py", "--list", str(payload))
    assert result.returncode == 0, result.stderr
    text = result.stdout
    assert "MR_IDS=7|12" in text
    assert "MR_7_SOURCE_BRANCH=feature-a" in text
    assert "MR_12_SOURCE_BRANCH=feature-b" in text
    assert (
        "MR_SIGNATURE=7:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa|"
        "12:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    ) in text
    assert "\nMR_IID=" not in text
    assert "MR_12_IID=12" in text


def test_gitlab_mr_has_code_delta_detects_empty_compare(tmp_path):
    empty = tmp_path / "empty.json"
    empty.write_text('{"commits": [], "diffs": []}', encoding="utf-8")
    filled = tmp_path / "filled.json"
    filled.write_text('{"commits": [{"id": "abc"}], "diffs": []}', encoding="utf-8")

    empty_rc = run_py("ci/gitlab_mr_has_code_delta.py", str(empty)).returncode
    filled_rc = run_py("ci/gitlab_mr_has_code_delta.py", str(filled)).returncode
    assert empty_rc == 1
    assert filled_rc == 0
