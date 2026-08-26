import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
COLLECT_SCRIPT = REPO_ROOT / "ci" / "collect_failure_bundle.sh"
ENABLE_SCRIPT = REPO_ROOT / "ci" / "enable_failure_coredumps.sh"


def _bash():
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("bash is required to exercise collect_failure_bundle.sh")
    return bash


def _write_executable(path: Path, content: str):
    path.write_text(content.replace("\r\n", "\n"), encoding="utf-8", newline="\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _bash_path(path: Path) -> str:
    """Convert a Windows path to a Git-Bash-friendly POSIX path when needed."""
    text = str(path.resolve()).replace("\\", "/")
    if len(text) >= 2 and text[1] == ":":
        return f"/{text[0].lower()}{text[2:]}"
    return text


def test_collect_script_contains_gcore_and_bundle_paths():
    source = COLLECT_SCRIPT.read_text(encoding="utf-8")
    assert "gcore" in source
    assert 'pgrep -x "${name}"' in source
    assert "fio" in source and "dpraid" in source
    assert "draid_kthreads" in source
    assert "is_kernel_thread" in source
    assert "draid_diag" in source
    assert "debugfs" in source
    assert "snapshot_kdump_artifacts" in source
    assert "snapshot_related_kworker_stacks" in source
    assert "kworker_stacks" in source
    assert "enable_draid_pending_debug.sh" in source
    assert "failure_bundle_" in source
    assert "draid.ko" in source
    assert "latest_bundle_summary.txt" in source
    assert "enable_failure_coredumps.sh" in source
    assert "exit 0" in source


def test_enable_draid_pending_debug_script_probes_module_params():
    pending = REPO_ROOT / "ci" / "enable_draid_pending_debug.sh"
    source = pending.read_text(encoding="utf-8")
    assert "raid1_pending_debug" in source
    assert "/sys/module/draid/parameters" in source
    assert "dynamic_debug" in source
    assert "DRAID_DYNDBG" in source
    assert "WHITELIST_PARAMS" in source
    # Must not blindly write counters named bare raid1_pending.
    assert "echo 1 >\"${PARAMS}/raid1_pending\"" not in source
    assert "exit 0" in source


def test_fio_triggers_live_bundle_on_eio():
    fio = (REPO_ROOT / "IO_Stress" / "lib" / "fio.sh").read_text(encoding="utf-8")
    assert "trigger_live_failure_bundle" in fio
    assert "fio_log_has_eio" in fio
    assert "fio_eio_live" in fio
    assert "collect_failure_bundle.sh" in fio
    assert "FIO_LIVE_BUNDLE_BG" in fio
    assert "live_collect_pending_" in fio
    assert "last_progress_ts=$(date +%s)" in fio


def test_collect_script_prefers_primary_kworker_filter():
    source = COLLECT_SCRIPT.read_text(encoding="utf-8")
    assert "matched_primary" in source
    assert "Primary filter" in source
    assert "preferred_live_bundle_path.txt" in source
    assert "live_bundle_${SAFE_KEY}.txt" in source


def test_wiring_references_failure_bundle():
    nvme = (REPO_ROOT / "nvme_raid_test.py").read_text(encoding="utf-8")
    remote = (REPO_ROOT / "ci" / "run_remote_test_and_collect.sh").read_text(encoding="utf-8")
    jenkins = (REPO_ROOT / "Jenkinsfile").read_text(encoding="utf-8")
    prepare = (REPO_ROOT / "ci" / "prepare_env.sh").read_text(encoding="utf-8")
    install = (REPO_ROOT / "ci" / "install_test_dependencies.sh").read_text(encoding="utf-8")

    assert "collect_failure_bundle" in nvme
    assert "resolve_failure_bundle_for_item" in nvme
    assert "find_live_failure_bundle" in nvme
    assert "collect_failure_bundle.sh" in nvme
    assert "add_allure_failure_bundle" in nvme
    assert "failure_gcore_summary_" in nvme
    assert "enable_draid_pending_debug" in nvme
    assert "collect_failure_bundle.sh" in remote
    assert "enable_draid_pending_debug.sh" in remote
    assert "failure_bundle_*.tar.gz" in remote
    assert "failure_bundle_*.tar.gz" in jenkins
    assert "allure-results/failure_bundle_*.tar.gz" in jenkins
    assert "enable_failure_coredumps.sh" in prepare
    assert "enable_draid_pending_debug.sh" in prepare
    assert "enable_failure_coredumps_early" in install
    assert "enable_failure_kdump.sh" in install
    assert "enable_draid_pending_debug.sh" in install
    assert "gdb" in install
    assert "enable_failure_coredumps.sh" in install


def test_resolve_failure_bundle_prefers_live_over_recollect(tmp_path, monkeypatch):
    import sys

    sys.path.insert(0, str(REPO_ROOT))
    import nvme_raid_test as runner

    base = tmp_path / "ws"
    bundles = base / "failure_bundles"
    bundles.mkdir(parents=True)
    live = bundles / "failure_bundle_10.0.0.8_basic_io_live.tar.gz"
    live.write_bytes(b"live-tar")
    (bundles / "live_bundle_basic_io.txt").write_text(str(live), encoding="utf-8")
    (bundles / "preferred_live_bundle_path.txt").write_text(str(live), encoding="utf-8")

    called = {"count": 0}

    def _fake_collect(*_args, **_kwargs):
        called["count"] += 1
        return str(bundles / "should_not_use.tar.gz")

    monkeypatch.setattr(runner, "collect_failure_bundle", _fake_collect)
    archive = runner.resolve_failure_bundle_for_item(str(base), "basic_io", exit_code=1)
    assert archive == str(live)
    assert called["count"] == 0


def test_add_allure_failure_bundle_prefers_live_path(tmp_path):
    import json
    import sys

    sys.path.insert(0, str(REPO_ROOT))
    import nvme_raid_test as runner

    base = tmp_path / "ws"
    allure_dir = base / "allure-results"
    allure_dir.mkdir(parents=True)
    bundles = base / "failure_bundles"
    bundles.mkdir()
    live = bundles / "failure_bundle_10.0.0.8_basic_io_1.tar.gz"
    live.write_bytes(b"live-tar")
    late = bundles / "failure_bundle_10.0.0.8_basic_io_2.tar.gz"
    late.write_bytes(b"late-tar")
    (bundles / "live_bundle_basic_io.txt").write_text(str(live), encoding="utf-8")
    (bundles / "latest_bundle_path.txt").write_text(str(late), encoding="utf-8")
    (bundles / "latest_bundle_summary.txt").write_text("live summary\n", encoding="utf-8")
    result_path = allure_dir / "abc-result.json"
    result_path.write_text(
        json.dumps(
            {
                "name": "Test_CI_basic_IO",
                "fullName": "test_items.test_ci_basic_io.Test_CI_basic_IO",
                "status": "failed",
                "labels": [{"name": "run_key", "value": "basic_io"}],
                "attachments": [],
            }
        ),
        encoding="utf-8",
    )

    runner.add_allure_failure_bundle("basic_io", str(base), item="basic_io")

    attached = (allure_dir / "failure_bundle_basic_io.tar.gz").read_bytes()
    assert attached == b"live-tar"


def test_enable_script_sets_ulimit_and_core_pattern():
    source = ENABLE_SCRIPT.read_text(encoding="utf-8")
    assert "ulimit -c unlimited" in source
    assert "kernel.core_pattern" in source
    assert "failure_bundles/cores" in source
    assert "ptrace_scope" in source
    assert "yama" in source
    assert "limits.d" in source
    assert "sysctl.d" in source
    assert "99-raid-nvme-coredump" in source
    assert "profile.d" in source
    assert "apport" in source


def test_collect_failure_bundle_smoke_with_fake_gcore(tmp_path):
    bash = _bash()
    remote_dir = tmp_path / "remote"
    remote_dir.mkdir()
    (remote_dir / "kernel_driver" / "drivers" / "draid").mkdir(parents=True)
    (remote_dir / "kernel_driver" / "drivers" / "draid" / "draid.ko").write_bytes(b"ko")
    (remote_dir / "IO_Stress" / "log" / "TestErrorLog").mkdir(parents=True)
    (remote_dir / "IO_Stress" / "log" / "TestErrorLog" / "err.log").write_text("boom\n", encoding="utf-8")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(
        bin_dir / "pgrep",
        """#!/usr/bin/env bash
if [ "$1" = "-x" ] && [ "$2" = "fio" ]; then
  printf '4242\\n'
  exit 0
fi
exit 1
""",
    )
    _write_executable(
        bin_dir / "gcore",
        """#!/usr/bin/env bash
# gcore -o cores/core.fio <pid>
out="$2"
pid="$3"
printf 'FAKECORE\\n' >"${out}.${pid}"
""",
    )
    _write_executable(
        bin_dir / "fio",
        """#!/usr/bin/env bash
if [ "$1" = "--version" ]; then
  echo 'fio-fake'
  exit 0
fi
exit 0
""",
    )

    env = os.environ.copy()
    env["PATH"] = f"{_bash_path(bin_dir)}{os.pathsep}{env.get('PATH', '')}"
    env["NODE_IP"] = "10.0.0.8"
    env["REMOTE_DIR"] = _bash_path(remote_dir)
    env["RUN_KEY"] = "smoke_mix"
    env["BUNDLE_REASON"] = "unit_test"

    result = subprocess.run(
        [bash, str(COLLECT_SCRIPT).replace("\\", "/")],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    bundles = list((remote_dir / "failure_bundles").glob("failure_bundle_*.tar.gz"))
    assert bundles, result.stdout + result.stderr
    latest = (remote_dir / "failure_bundles" / "latest_bundle_path.txt").read_text(encoding="utf-8").strip()
    assert latest.endswith(".tar.gz")
    assert "gcore fio pid=4242" in result.stdout or "gcore fio pid=4242" in result.stderr

    # Unpack and confirm core + README landed.
    extract_dir = tmp_path / "extract"
    extract_dir.mkdir()
    unpack = subprocess.run(
        [
            bash,
            "-lc",
            f"tar -xzf '{_bash_path(bundles[0])}' -C '{_bash_path(extract_dir)}'",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert unpack.returncode == 0, unpack.stderr + unpack.stdout
    work = next(extract_dir.iterdir())
    assert (work / "README.txt").is_file()
    cores = list((work / "cores").glob("core.fio.*"))
    assert cores, "expected gcore output under cores/"
    assert cores[0].read_text(encoding="utf-8").startswith("FAKECORE")
    assert (work / "draid.ko").is_file()


def test_add_allure_failure_bundle_attaches_tar_and_summary(tmp_path):
    import json
    import sys

    sys.path.insert(0, str(REPO_ROOT))
    import nvme_raid_test as runner

    base = tmp_path / "ws"
    allure_dir = base / "allure-results"
    allure_dir.mkdir(parents=True)
    bundles = base / "failure_bundles"
    bundles.mkdir()
    archive = bundles / "failure_bundle_10.0.0.8_basic_io_1.tar.gz"
    archive.write_bytes(b"fake-tar")
    (bundles / "latest_bundle_path.txt").write_text(str(archive), encoding="utf-8")
    (bundles / "latest_bundle_summary.txt").write_text(
        "no live fio\n", encoding="utf-8"
    )
    result_path = allure_dir / "abc-result.json"
    result_path.write_text(
        json.dumps(
            {
                "name": "Test_CI_basic_IO",
                "fullName": "test_items.test_ci_basic_io.Test_CI_basic_IO",
                "status": "failed",
                "labels": [{"name": "run_key", "value": "basic_io"}],
                "attachments": [],
            }
        ),
        encoding="utf-8",
    )

    runner.add_allure_failure_bundle(
        "basic_io", str(base), item="basic_io", archive_path=str(archive)
    )

    result = json.loads(result_path.read_text(encoding="utf-8"))
    names = {item["name"] for item in result["attachments"]}
    assert "failure_gcore_bundle_basic_io" in names
    assert "failure_gcore_summary_basic_io" in names
    assert (allure_dir / "failure_bundle_basic_io.tar.gz").is_file()
    assert (allure_dir / "failure_gcore_summary_basic_io.txt").read_text(
        encoding="utf-8"
    ).startswith("no live fio")
