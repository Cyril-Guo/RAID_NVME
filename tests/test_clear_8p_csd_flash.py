import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CLEAR_SCRIPT = REPO_ROOT / "ci" / "clear_8p_csd_flash.sh"

SHOW_HEADER = (
    "ID CONTROLLER MODEL              SERIAL NUMBER         "
    "NUMA STAT     FW_VER  DRIVER_VER"
)
SHOW_C0 = (
    "0  DAPUSTOR DPFP62AA0R1G00105G0B0 SN-825F661183A26F54  "
    "0    Optimal  FH00310 2.8.1"
)
SHOW_C1 = (
    "1  DAPUSTOR DPFP62AA0R1G00105G0B0 SN-FCD5391A0A17187F  "
    "0    Optimal  FH00310 2.8.1"
)


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
    dpraid_home = tmp_path / "dpraid_home"
    jenkins_root = tmp_path / "jenkins_root"
    dpraid_home.mkdir(parents=True, exist_ok=True)
    jenkins_root.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["PATH"] = f"{tmp_path}{os.pathsep}{env.get('PATH', '')}"
    env["NODE_IP"] = "192.168.22.134"
    env["DPRAID_HOME"] = str(dpraid_home).replace("\\", "/")
    env["JENKINS_DUT_ROOT"] = str(jenkins_root).replace("\\", "/")
    env["DPRAID_MIN_FREE_MB"] = "1"
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
        _fake_dpraid([SHOW_HEADER, SHOW_C0]),
    )

    result = _run_clear(tmp_path, {"DPRAID_BIN": str(fake_dpraid).replace("\\", "/")})

    assert result.returncode == 0, result.stderr + result.stdout
    assert "dpraid workspace ready" in result.stdout
    assert "dpraid show" in result.stdout
    assert "found 1 controller(s): /c0" in result.stdout
    assert "[OK] /c0 flash-clear --with-cache --force succeeded" in result.stdout
    assert "flash-clear /c1" not in result.stdout
    assert (tmp_path / "dpraid_home" / "jobs").is_dir()


def test_clear_fails_when_disk_too_full(tmp_path):
    fake_dpraid = tmp_path / "dpraid"
    _write_executable(
        fake_dpraid,
        _fake_dpraid([SHOW_HEADER, SHOW_C0]),
    )

    result = _run_clear(
        tmp_path,
        {
            "DPRAID_BIN": str(fake_dpraid).replace("\\", "/"),
            # Force the free-space gate without depending on real disk usage.
            "DPRAID_MIN_FREE_MB": "999999999",
        },
    )

    assert result.returncode != 0
    assert "not enough free disk for dpraid jobs" in result.stderr


def test_clear_runs_flash_clear_on_two_controllers(tmp_path):
    fake_dpraid = tmp_path / "dpraid"
    _write_executable(
        fake_dpraid,
        _fake_dpraid([SHOW_HEADER, SHOW_C0, SHOW_C1]),
    )

    result = _run_clear(tmp_path, {"DPRAID_BIN": str(fake_dpraid).replace("\\", "/")})

    assert result.returncode == 0, result.stderr + result.stdout
    assert "found 2 controller(s): /c0 /c1" in result.stdout
    assert "[OK] /c0 flash-clear --with-cache --force succeeded" in result.stdout
    assert "[OK] /c1 flash-clear --with-cache --force succeeded" in result.stdout


def test_clear_ignores_numeric_rows_outside_controller_table(tmp_path):
    fake_dpraid = tmp_path / "dpraid"
    _write_executable(
        fake_dpraid,
        _fake_dpraid(
            [
                SHOW_HEADER,
                SHOW_C0,
                "",
                "DID STATE SIZE",
                "0 UnGo 6400GB",
                "1 UnGo 6400GB",
            ]
        ),
    )

    result = _run_clear(tmp_path, {"DPRAID_BIN": str(fake_dpraid).replace("\\", "/")})

    assert result.returncode == 0, result.stderr + result.stdout
    assert "found 1 controller(s): /c0" in result.stdout
    assert "/c1 flash-clear" not in result.stdout


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
    assert "no controllers parsed from dpraid show" in result.stderr
