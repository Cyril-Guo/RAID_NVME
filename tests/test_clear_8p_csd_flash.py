import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CLEAR_SCRIPT = REPO_ROOT / "ci" / "clear_8p_csd_flash.sh"


def _bash():
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("bash is required to exercise clear_8p_csd_flash.sh")
    return bash


def _write_executable(path: Path, content: str):
    path.write_text(content.replace("\r\n", "\n"), encoding="utf-8", newline="\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _fake_dpraid(show_lines: list[str]) -> str:
    body = "\n".join(show_lines)
    return f"""#!/usr/bin/env bash
set -eu
if [ "${{1:-}}" = "show" ]; then
  cat <<'EOF'
{body}
EOF
  exit 0
fi
if [ "${{2:-}}" = "flash-clear" ] && [ "${{3:-}}" = "--with-cache" ] && [ "${{4:-}}" = "--force" ]; then
  echo "flash-clear ${1} --with-cache --force"
  exit 0
fi
echo "unexpected: $*" >&2
exit 1
"""


def _run_clear(tmp_path, env_extra):
    bash = _bash()
    env = os.environ.copy()
    env["PATH"] = f"{tmp_path}{os.pathsep}{env.get('PATH', '')}"
    env["NODE_IP"] = "192.168.22.134"
    env.update(env_extra)
    return subprocess.run(
        [bash, str(CLEAR_SCRIPT).replace("\\", "/")],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_clear_runs_flash_clear_on_single_controller(tmp_path):
    fake_dpraid = tmp_path / "dpraid"
    _write_executable(
        fake_dpraid,
        _fake_dpraid(["0 Online RAID Controller 0"]),
    )

    result = _run_clear(tmp_path, {"DPRAID_BIN": str(fake_dpraid).replace("\\", "/")})

    assert result.returncode == 0, result.stderr + result.stdout
    assert "dpraid show" in result.stdout
    assert "flash-clear controllers: 0" in result.stdout
    assert "flash-clear /c0 --with-cache --force" in result.stdout


def test_clear_runs_flash_clear_on_two_controllers(tmp_path):
    fake_dpraid = tmp_path / "dpraid"
    _write_executable(
        fake_dpraid,
        _fake_dpraid(
            [
                "0 Online RAID Controller 0",
                "1 Online RAID Controller 1",
            ]
        ),
    )

    result = _run_clear(tmp_path, {"DPRAID_BIN": str(fake_dpraid).replace("\\", "/")})

    assert result.returncode == 0, result.stderr + result.stdout
    assert "flash-clear controllers: 0 1" in result.stdout
    assert "flash-clear /c0 --with-cache --force" in result.stdout
    assert "flash-clear /c1 --with-cache --force" in result.stdout


def test_clear_fails_when_dpraid_show_fails(tmp_path):
    fake_dpraid = tmp_path / "dpraid"
    _write_executable(
        fake_dpraid,
        """#!/usr/bin/env bash
echo "dpraid unavailable" >&2
exit 1
""",
    )

    result = _run_clear(tmp_path, {"DPRAID_BIN": str(fake_dpraid).replace("\\", "/")})

    assert result.returncode != 0
    assert "dpraid show failed" in result.stderr


def test_clear_fails_when_no_controllers_in_show_output(tmp_path):
    fake_dpraid = tmp_path / "dpraid"
    _write_executable(
        fake_dpraid,
        """#!/usr/bin/env bash
if [ "${1:-}" = "show" ]; then
  echo "No controllers"
  exit 0
fi
exit 1
""",
    )

    result = _run_clear(tmp_path, {"DPRAID_BIN": str(fake_dpraid).replace("\\", "/")})

    assert result.returncode != 0
    assert "no draid controllers found" in result.stderr
