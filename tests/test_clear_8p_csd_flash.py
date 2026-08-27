import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CLEAR_SCRIPT = REPO_ROOT / "ci" / "clear_8p_csd_flash.sh"
DAPU_LINE = (
    "0000:95:00.0 Non-Volatile memory controller: "
    "Shenzhen DAPU Microelectronics Co., Ltd Device 50d1 (rev 01)"
)
DAPU_LINE_2 = (
    "0000:96:00.0 Non-Volatile memory controller: "
    "Shenzhen DAPU Microelectronics Co., Ltd Device 50d1 (rev 01)"
)


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
    env["SYSFS_ROOT"] = str(tmp_path / "sys").replace("\\", "/")
    env["NVME_BIN"] = str(tmp_path / "nvme").replace("\\", "/")
    env.update(env_extra)
    if not (tmp_path / "nvme").exists():
        _write_executable(tmp_path / "nvme", "#!/usr/bin/env bash\nexit 0\n")
    return subprocess.run(
        [bash, str(CLEAR_SCRIPT).replace("\\", "/")],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _fake_lspci_listing(*lines: str) -> str:
    joined = "\n".join(lines)
    return f"""#!/usr/bin/env bash
if [ "${{1:-}}" = "-Dnn" ] || [ "${{1:-}}" = "-nn" ]; then
cat <<'EOF'
{joined}
EOF
  exit 0
fi
"""


def _fake_lspci_with_driver(bindings: dict[str, str]) -> str:
    script = _fake_lspci_listing(DAPU_LINE, DAPU_LINE_2)
    script += """
lookup_driver() {
  case "${1:-}" in
"""
    for bdf, driver in bindings.items():
        short = bdf.replace("0000:", "")
        detail = (
            f"Kernel driver in use: {driver}"
            if driver
            else "Kernel modules: draid-nvme, nvme"
        )
        script += f'    {bdf}|{short}) printf "%s\\n" "{detail}"; return 0 ;;\n'
    script += """    *) return 1 ;;
  esac
}
if [ "${1:-}" = "-s" ]; then
  addr="${2:-}"
  if [ "${3:-}" = "-k" ] || [ "${4:-}" = "-k" ]; then
    lookup_driver "${addr}" || true
    exit 0
  fi
fi
exit 0
"""
    return script


def _dev_map(*pairs: tuple[str, str]) -> str:
    return ",".join(f"{bdf}={dev}" for bdf, dev in pairs)


def test_clear_maps_dirty_dapu_csd_without_draid_nvme_driver(tmp_path):
    fake_lspci = tmp_path / "lspci"
    _write_executable(
        fake_lspci,
        _fake_lspci_with_driver(
            {
                "0000:95:00.0": "",
                "0000:96:00.0": "",
            }
        ),
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
            "LSPCI_BIN": str(fake_lspci).replace("\\", "/"),
            "FLASH_CLEAR_SCRIPT": str(fake_flash_clear).replace("\\", "/"),
            "DRAID_ACCEL_DEV_MAP": _dev_map(
                ("0000:95:00.0", "/dev/draid_dbg_accel0"),
                ("0000:96:00.0", "/dev/draid_dbg_accel1"),
            ),
        },
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert "confirm=CLEAR" in result.stdout
    assert "devices=/dev/draid_dbg_accel0 /dev/draid_dbg_accel1" in result.stdout
    assert "missing Kernel driver in use: draid-nvme" in result.stdout


def test_clear_skips_dapu_csd_already_bound_to_draid_nvme(tmp_path):
    fake_lspci = tmp_path / "lspci"
    _write_executable(
        fake_lspci,
        _fake_lspci_with_driver(
            {
                "0000:95:00.0": "draid-nvme",
                "0000:96:00.0": "draid-nvme",
            }
        ),
    )

    result = _run_clear(
        tmp_path,
        {
            "LSPCI_BIN": str(fake_lspci).replace("\\", "/"),
        },
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert "no dirty DAPU CSD devices" in result.stdout
    assert "skip clean DAPU CSD" in result.stdout


def test_clear_only_dirty_dapu_csd_is_cleared(tmp_path):
    fake_lspci = tmp_path / "lspci"
    _write_executable(
        fake_lspci,
        _fake_lspci_with_driver(
            {
                "0000:95:00.0": "draid-nvme",
                "0000:96:00.0": "",
            }
        ),
    )
    fake_flash_clear = tmp_path / "flash-clear.sh"
    _write_executable(
        fake_flash_clear,
        """#!/usr/bin/env bash
read -r confirm
printf 'devices=%s\\n' "$*"
""",
    )

    result = _run_clear(
        tmp_path,
        {
            "LSPCI_BIN": str(fake_lspci).replace("\\", "/"),
            "FLASH_CLEAR_SCRIPT": str(fake_flash_clear).replace("\\", "/"),
            "DRAID_ACCEL_DEV_MAP": _dev_map(("0000:96:00.0", "/dev/draid_dbg_accel6")),
        },
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert "devices=/dev/draid_dbg_accel6" in result.stdout
    assert "skip clean DAPU CSD 0000:95:00.0" in result.stdout


def test_clear_skips_when_no_dapu_csd_devices(tmp_path):
    fake_lspci = tmp_path / "lspci"
    _write_executable(
        fake_lspci,
        """#!/usr/bin/env bash
printf '%s\\n' '0000:01:00.0 NVMe controller: Other Vendor'
""",
    )

    result = _run_clear(
        tmp_path,
        {
            "LSPCI_BIN": str(fake_lspci).replace("\\", "/"),
        },
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert "no dirty DAPU CSD devices" in result.stdout
