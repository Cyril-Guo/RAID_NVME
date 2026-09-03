"""Exercise the actual pytest/Allure plugin with a harmless dummy test."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


def test_context_hook_and_real_fixture_evidence(tmp_path, monkeypatch):
    pytest.importorskip("allure_pytest")
    from ci import junit_to_allure, mark_allure_target_context
    import nvme_raid_test
    shutil.copy2(Path(__file__).resolve().parents[1] / "conftest.py", tmp_path / "conftest.py")
    (tmp_path / "test_dummy.py").write_text(
        "import allure, pytest\n"
        "@pytest.fixture\n"
        "def context():\n"
        "    allure.attach('setup', name='setup evidence')\n"
        "    yield\n"
        "    allure.attach('teardown', name='teardown evidence')\n"
        "def test_dummy(context):\n"
        "    assert True\n", encoding="utf-8")
    env = dict(os.environ, RAID_NVME_RUN_KEY="mix__2", RAID_NVME_ITEM="mix", RAID_NVME_RUN_ORDER="2")
    completed = subprocess.run([sys.executable, "-m", "pytest", "-q", "test_dummy.py",
                               "--alluredir=allure-results", "--junitxml=report_mix__2.xml"],
                              cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    root = tmp_path / "allure-results"
    raw = json.loads(next(root.glob("*-result.json")).read_text(encoding="utf-8"))
    assert any(l == {"name": "run_key", "value": "mix__2"} for l in raw["labels"])
    for path in root.glob("*-container.json"):
        assert "raid_nvme_run_context" not in path.read_text(encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    nvme_raid_test.merge_junit_reports(["mix__2"], "report_192.168.22.134.xml")
    mark_allure_target_context.main([str(root), "192.168.22.134"])
    junit_to_allure.main()
    assert len(list(root.glob("*-result.json"))) == 1
    result = json.loads(next(root.glob("*-result.json")).read_text(encoding="utf-8"))
    assert result["status"] == "passed"
    logs = next(s for s in result["steps"] if s["name"] == "日志收集")["attachments"]
    assert {"setup evidence", "teardown evidence"} <= {a["name"] for a in logs}
    assert all((root / a["source"]).is_file() for a in logs)
    for path in root.glob("*-container.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert not data.get("befores") and not data.get("afters")
