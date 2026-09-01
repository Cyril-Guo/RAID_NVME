"""Lightweight parser checks mirroring MachineCheck link/AER extraction rules."""

import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest


def extract_link_field(text, section, field):
    pattern = re.compile(
        rf"^[ \t]*{re.escape(section)}:.*?\b{re.escape(field)}[ \t]+([^,\n]+)",
        re.MULTILINE,
    )
    match = pattern.search(text)
    if not match:
        return ""
    value = match.group(1).strip()
    value = re.sub(r"\s*\(.*\)$", "", value)
    return value


def extract_aer_field(text, section):
    pattern = re.compile(rf"^[ \t]*{re.escape(section)}:[ \t]*(.*)$", re.MULTILINE)
    match = pattern.search(text)
    if not match:
        return ""
    return " ".join(match.group(1).split())


SAMPLE = """
e1:00.0 Non-Volatile memory controller: Shenzhen DAPU Microelectronics Co., Ltd NVMe SSD Controller DPU600
        LnkCap: Port #0, Speed 16GT/s, Width x4, ASPM L1, Exit Latency L0s unlimited, L1 <64us
        LnkSta: Speed 16GT/s (ok), Width x4 (ok)
        Capabilities: [100 v2] Advanced Error Reporting
                UESta:  DLP- SDES- TLP- FCP- CmpltTO- CmpltAbrt- UnxCmplt- RxOF- MalfTLP- ECRC- UnsupReq- ACSViol-
                CESta:  RxErr- BadTLP- BadDLLP- Rollover- Timeout- AdvNonFatalErr-
"""

SAMPLE_CHANGED = """
        LnkCap: Port #0, Speed 16GT/s, Width x4
        LnkSta: Speed 8GT/s (downgraded), Width x2 (downgraded)
                UESta:  DLP- SDES- TLP+ FCP-
                CESta:  RxErr+ BadTLP- BadDLLP-
"""


def test_extract_link_records_raw_values():
    assert extract_link_field(SAMPLE, "LnkCap", "Speed") == "16GT/s"
    assert extract_link_field(SAMPLE, "LnkCap", "Width") == "x4"
    assert extract_link_field(SAMPLE, "LnkSta", "Speed") == "16GT/s"
    assert extract_link_field(SAMPLE, "LnkSta", "Width") == "x4"


def test_extract_link_records_changed_values_for_diff():
    assert extract_link_field(SAMPLE_CHANGED, "LnkSta", "Speed") == "8GT/s"
    assert extract_link_field(SAMPLE_CHANGED, "LnkSta", "Width") == "x2"


def test_extract_aer_records_raw_flag_tokens():
    assert "TLP-" in extract_aer_field(SAMPLE, "UESta")
    assert "RxErr-" in extract_aer_field(SAMPLE, "CESta")
    assert "TLP+" in extract_aer_field(SAMPLE_CHANGED, "UESta")
    assert "RxErr+" in extract_aer_field(SAMPLE_CHANGED, "CESta")


def test_machinecheck_pcie_probe_is_bounded_and_reports_live_bdf_progress():
    source = Path("MachineCheck/MachineCheck.sh").read_text(encoding="utf-8")

    assert 'MACHINECHECK_PCIE_TIMEOUT_SECONDS:-15' in source
    assert 'timeout --kill-after=2s "${pcie_timeout_seconds}s"' in source
    assert "[MACHINECHECK] probe start bdf=" in source
    assert "[MACHINECHECK] probe finish bdf=" in source
    assert "[MACHINECHECK] probe timeout bdf=" in source
    assert "machinecheck_rc" in source


def _bash_path(path):
    text = str(Path(path).resolve()).replace("\\", "/")
    if len(text) >= 2 and text[1] == ":":
        return f"/{text[0].lower()}{text[2:]}"
    return text


def _write_executable(path, content):
    path.write_text(content, encoding="utf-8", newline="\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def test_machinecheck_times_out_stuck_lspci_and_returns_124(tmp_path):
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("bash is required to exercise MachineCheck.sh")

    machine_dir = tmp_path / "MachineCheck"
    fake_bin = tmp_path / "bin"
    machine_dir.mkdir()
    fake_bin.mkdir()
    shutil.copy2("MachineCheck/MachineCheck.sh", machine_dir / "MachineCheck.sh")
    (machine_dir / "install_flag").write_text("done\n", encoding="utf-8")

    _write_executable(
        fake_bin / "lspci",
        """#!/usr/bin/env bash
case "${1:-}" in
    --version) echo 'lspci fake 1.0' ;;
    -Dnn) echo '0000:17:00.0 Non-Volatile memory controller [0108]: DAPU test [1e3b:0600]' ;;
    -s) sleep 5 ;;
esac
""",
    )
    _write_executable(fake_bin / "nvme", "#!/usr/bin/env bash\n[ \"${1:-}\" = --version ] && echo 'nvme fake 1.0'\n")
    _write_executable(fake_bin / "lscpu", "#!/usr/bin/env bash\necho 'Model name: Fake CPU'\necho 'Socket(s): 1'\n")
    _write_executable(fake_bin / "lsblk", "#!/usr/bin/env bash\necho 'sda disk'\n")
    _write_executable(fake_bin / "tput", "#!/usr/bin/env bash\nexit 0\n")

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env.get('PATH', '')}"
    env["MACHINECHECK_PCIE_TIMEOUT_SECONDS"] = "1"
    result = subprocess.run(
        [bash, _bash_path(machine_dir / "MachineCheck.sh")],
        env=env,
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )

    assert result.returncode == 124, result.stdout + result.stderr
    assert "[MACHINECHECK] probe start bdf=0000:17:00.0" in result.stderr
    assert "[MACHINECHECK] probe timeout bdf=0000:17:00.0" in result.stderr
    assert "link:" in result.stdout and "LnkCap_Speed=NA" in result.stdout
