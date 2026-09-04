import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_SCRIPT = REPO_ROOT / "ci" / "run_remote_test_and_collect.sh"


def _bash():
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("bash is required to exercise run_remote_test_and_collect.sh")
    return bash


def _write_executable(path: Path, content: str):
    path.write_text(content.replace("\r\n", "\n"), encoding="utf-8", newline="\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _bash_path(path: Path) -> str:
    text = str(path.resolve()).replace("\\", "/")
    if len(text) >= 2 and text[1] == ":":
        return f"/{text[0].lower()}{text[2:]}"
    return text


def test_remote_test_no_longer_gates_on_allow_destructive_fio():
    source = RUN_SCRIPT.read_text(encoding="utf-8")
    jenkinsfile = (REPO_ROOT / "Jenkinsfile").read_text(encoding="utf-8")

    assert "ALLOW_DESTRUCTIVE_FIO" not in source
    assert "ALLOW_DESTRUCTIVE_FIO" not in jenkinsfile
    assert "enable_failure_coredumps.sh" in source
    assert "ulimit -c unlimited" in source
    assert "python3 nvme_raid_test.py" in source
    assert "TEST_IDLE_TIMEOUT_MINUTES=${TEST_IDLE_TIMEOUT_MINUTES}" in source


def test_remote_cleanup_is_bounded_and_failure_is_recorded_before_copy():
    source = RUN_SCRIPT.read_text(encoding="utf-8")

    assert 'cleanup_timeout_seconds="${CLEANUP_TIMEOUT_SECONDS:-900}"' in source
    assert "run_cleanup_command" in source
    assert "REPORT_COPY_TIMEOUT_SECONDS" in source
    failed_marker = source.index('echo "TEST_EXECUTION_STATUS=failed"')
    report_copy = source.index('echo "[${NODE_IP}] copy back reports"')
    assert failed_marker < report_copy


@pytest.mark.parametrize("reuse_live_bundle", [True, False])
def test_failed_remote_test_copies_one_live_or_fallback_bundle(tmp_path, reuse_live_bundle):
    fake_ssh = tmp_path / "fake-ssh"
    fake_scp = tmp_path / "fake-scp"
    fake_setsid = tmp_path / "setsid"
    ssh_log = tmp_path / "ssh.log"
    scp_log = tmp_path / "scp.log"
    live_bundle = "/remote/work/failure_bundles/failure_bundle_10.0.0.8_mix_2_live.tar.gz"
    fallback_bundle = "/remote/work/failure_bundles/failure_bundle_10.0.0.8_remote_runner.tar.gz"
    collect_marker = tmp_path / "collect.marker"

    _write_executable(
        fake_ssh,
        f"""#!/usr/bin/env bash
set -eu
printf '%s\\n' "$*" >> "${{FAKE_SSH_LOG}}"
case "$*" in
    *"python3 nvme_raid_test.py"*) exit 7 ;;
    *"preferred_live_bundle_path.txt"*)
        [ "${{FAKE_REUSE_LIVE}}" = "1" ] && printf '%s\\n' "{live_bundle}"
        ;;
    *"latest_bundle_path.txt"*)
        [ -f "${{FAKE_COLLECT_MARKER}}" ] && printf '%s\\n' "{fallback_bundle}"
        ;;
    *"test -f '{live_bundle}'"*) [ "${{FAKE_REUSE_LIVE}}" = "1" ] ;;
    *"test -f '{fallback_bundle}'"*) [ -f "${{FAKE_COLLECT_MARKER}}" ] ;;
    *"RUN_KEY=remote_runner"*) : > "${{FAKE_COLLECT_MARKER}}" ;;
    *"io_progress_signature.sh"*) sleep 1; printf 'stable-signature\\n' ;;
esac
exit 0
""",
    )
    _write_executable(
        fake_scp,
        """#!/usr/bin/env bash
set -eu
printf '%s\\n' "$*" >> "${FAKE_SCP_LOG}"
exit 0
""",
    )
    _write_executable(
        fake_setsid,
        """#!/usr/bin/env bash
exec "$@"
""",
    )

    env = os.environ.copy()
    env.update(
        {
            "NODE_IP": "10.0.0.8",
            "TARGET_USER": "root",
            "REMOTE_DIR": "/remote/work",
            "REMOTE_SSH_COMMAND": _bash_path(fake_ssh),
            "REMOTE_SCP_COMMAND": _bash_path(fake_scp),
            "TEST_IDLE_TIMEOUT_MINUTES": "1",
            "FAKE_SSH_LOG": _bash_path(ssh_log),
            "FAKE_SCP_LOG": _bash_path(scp_log),
            "FAKE_COLLECT_MARKER": _bash_path(collect_marker),
            "FAKE_REUSE_LIVE": "1" if reuse_live_bundle else "0",
            "PATH": f"{tmp_path}{os.pathsep}{env.get('PATH', '')}",
        }
    )
    result = subprocess.run(
        [_bash(), _bash_path(RUN_SCRIPT)],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )

    assert result.returncode == 7, result.stdout + result.stderr
    ssh_calls = ssh_log.read_text(encoding="utf-8")
    expected_bundle = live_bundle if reuse_live_bundle else fallback_bundle
    if reuse_live_bundle:
        assert "reuse live EIO failure bundle" in result.stdout
        assert "no reusable live EIO bundle" not in result.stdout
        assert "RUN_KEY=remote_runner" not in ssh_calls
    else:
        assert "no reusable live EIO bundle; collect fallback" in result.stdout
        assert "RUN_KEY=remote_runner" in ssh_calls
    scp_calls = scp_log.read_text(encoding="utf-8")
    assert f"root@10.0.0.8:{expected_bundle}" in scp_calls
    assert "failure_bundle_*" not in scp_calls
