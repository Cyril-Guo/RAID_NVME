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


def test_clear_8p_maps_namespaces_and_feeds_clear(tmp_path):
    bash = _bash()
    fake_lsblk = tmp_path / "lsblk"
    _write_executable(
        fake_lsblk,
        """#!/usr/bin/env bash
printf '%s\\n' 'nvme0n1 8P disk'
printf '%s\\n' 'nvme1n1 8.0P disk'
printf '%s\\n' 'nvme2n1 5.8T disk'
printf '%s\\n' 'nvme0n1 8P disk'
""",
    )
    fake_flash_clear = tmp_path / "flash-clear.sh"
    _write_executable(
        fake_flash_clear,
        """#!/usr/bin/env bash
read -r confirm
printf 'confirm=%s\\n' "$confirm"
printf 'devices=%s\\n' "$*"
""",
    )
    fake_nvme = tmp_path / "nvme"
    _write_executable(fake_nvme, "#!/usr/bin/env bash\nexit 0\n")

    env = os.environ.copy()
    env["PATH"] = f"{tmp_path}{os.pathsep}{env.get('PATH', '')}"
    env["LSBLK_BIN"] = str(fake_lsblk).replace("\\", "/")
    env["FLASH_CLEAR_SCRIPT"] = str(fake_flash_clear).replace("\\", "/")
    env["NODE_IP"] = "192.168.22.134"

    result = subprocess.run(
        [bash, str(CLEAR_SCRIPT).replace("\\", "/")],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert "confirm=CLEAR" in result.stdout
    assert "devices=/dev/nvme0 /dev/nvme1" in result.stdout
    assert "no 8P disks found" not in result.stdout


def test_clear_8p_skips_when_no_matching_disks(tmp_path):
    bash = _bash()
    fake_lsblk = tmp_path / "lsblk"
    _write_executable(
        fake_lsblk,
        """#!/usr/bin/env bash
printf '%s\\n' 'nvme2n1 5.8T disk'
""",
    )
    env = os.environ.copy()
    env["LSBLK_BIN"] = str(fake_lsblk).replace("\\", "/")
    env["NODE_IP"] = "192.168.22.134"

    result = subprocess.run(
        [bash, str(CLEAR_SCRIPT).replace("\\", "/")],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert "no 8P disks found; skip CSD flash clear" in result.stdout
