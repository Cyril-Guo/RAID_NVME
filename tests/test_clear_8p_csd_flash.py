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


def _run_clear(tmp_path, env_extra):
    bash = _bash()
    env = os.environ.copy()
    env["PATH"] = f"{tmp_path}{os.pathsep}{env.get('PATH', '')}"
    env["NODE_IP"] = "192.168.22.134"
    env["DRAID_SKIP_DEVICE_CHECK"] = "1"
    env.update(env_extra)
    return subprocess.run(
        [bash, str(CLEAR_SCRIPT).replace("\\", "/")],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_clear_8p_maps_namespaces_and_feeds_clear(tmp_path):
    fake_lsblk = tmp_path / "lsblk"
    _write_executable(
        fake_lsblk,
        """#!/usr/bin/env bash
printf '%s\\n' 'nvme0n1 8P disk'
printf '%s\\n' 'nvme1n1 9.0P disk'
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
    _write_executable(
        tmp_path / "nvme",
        """#!/usr/bin/env bash
if [ "${1:-}" = "list" ]; then
  printf '%s\\n' 'Node SN Model Namespace Usage Format FW'
  exit 0
fi
exit 0
""",
    )

    result = _run_clear(
        tmp_path,
        {
            "LSBLK_BIN": str(fake_lsblk).replace("\\", "/"),
            "NVME_BIN": str(tmp_path / "nvme").replace("\\", "/"),
            "FLASH_CLEAR_SCRIPT": str(fake_flash_clear).replace("\\", "/"),
        },
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert "confirm=CLEAR" in result.stdout
    assert "devices=/dev/draid_dbg_accel0 /dev/draid_dbg_accel1" in result.stdout
    assert "no dirty-CSD" not in result.stdout


def test_clear_9p_variant_is_detected(tmp_path):
    fake_lsblk = tmp_path / "lsblk"
    _write_executable(fake_lsblk, "#!/usr/bin/env bash\nprintf '%s\\n' 'nvme3n1 9.01P disk'\n")
    fake_flash_clear = tmp_path / "flash-clear.sh"
    _write_executable(
        fake_flash_clear,
        """#!/usr/bin/env bash
read -r confirm
printf 'confirm=%s\\n' "$confirm"
printf 'devices=%s\\n' "$*"
""",
    )
    _write_executable(tmp_path / "nvme", "#!/usr/bin/env bash\nexit 0\n")

    result = _run_clear(
        tmp_path,
        {
            "LSBLK_BIN": str(fake_lsblk).replace("\\", "/"),
            "NVME_BIN": str(tmp_path / "nvme").replace("\\", "/"),
            "FLASH_CLEAR_SCRIPT": str(fake_flash_clear).replace("\\", "/"),
        },
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert "devices=/dev/draid_dbg_accel3" in result.stdout
    assert "size=9.01P" in result.stdout


def test_clear_detects_dirty_csd_from_nvme_list_when_lsblk_is_clean(tmp_path):
    fake_lsblk = tmp_path / "lsblk"
    _write_executable(
        fake_lsblk,
        """#!/usr/bin/env bash
printf '%s\\n' 'nvme5n1 6.4T disk'
printf '%s\\n' 'nvme6n1 6.4T disk'
""",
    )
    fake_nvme = tmp_path / "nvme"
    _write_executable(
        fake_nvme,
        """#!/usr/bin/env bash
if [ "${1:-}" = "list" ]; then
cat <<'EOF'
Node             SN                   Model                                    Namespace Usage                      Format           FW Rev
---------------- -------------------- ---------------------------------------- --------- -------------------------- ---------------- --------
/dev/nvme5n1     SN5                  DAPUSTOR DPFP62AA                        1           0.00   B /   9.01  PB      4 KiB + 16 B   FC003104
/dev/nvme6n1     SN6                  DAPUSTOR DPFP62AA                        1           0.00   B /   9.01  PB      4 KiB + 16 B   FC003104
/dev/nvme7n1     SN7                  DAPUSTOR DPRD3100                        1           6.40  TB /   6.40  TB    512   B +  0 B   1.0
EOF
  exit 0
fi
exit 0
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

    result = _run_clear(
        tmp_path,
        {
            "LSBLK_BIN": str(fake_lsblk).replace("\\", "/"),
            "NVME_BIN": str(fake_nvme).replace("\\", "/"),
            "FLASH_CLEAR_SCRIPT": str(fake_flash_clear).replace("\\", "/"),
        },
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert "confirm=CLEAR" in result.stdout
    assert "devices=/dev/draid_dbg_accel5 /dev/draid_dbg_accel6" in result.stdout
    assert "via nvme-list" in result.stdout


def test_clear_8p_skips_when_no_matching_disks(tmp_path):
    fake_lsblk = tmp_path / "lsblk"
    _write_executable(fake_lsblk, "#!/usr/bin/env bash\nprintf '%s\\n' 'nvme2n1 5.8T disk'\n")
    fake_nvme = tmp_path / "nvme"
    _write_executable(
        fake_nvme,
        """#!/usr/bin/env bash
if [ "${1:-}" = "list" ]; then
printf '%s\\n' '/dev/nvme2n1 SN2 MODEL 1 1.00 TB / 5.80 TB 512 B + 0 B FW'
exit 0
fi
exit 0
""",
    )

    result = _run_clear(
        tmp_path,
        {
            "LSBLK_BIN": str(fake_lsblk).replace("\\", "/"),
            "NVME_BIN": str(fake_nvme).replace("\\", "/"),
        },
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert "no dirty-CSD disks found via lsblk or nvme list; skip CSD flash clear" in result.stdout
