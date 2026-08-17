"""MachineCheck whitelist fingerprint comparisons."""

from pathlib import Path
import subprocess
import textwrap


FINGERPRINT_SNIPPET = r'''
machinecheck_fingerprint() {
    local file="$1"
    sed 's/[[:space:]]\+/ /g; s/^ //; s/ $//' "$file" | awk '
        $1 == "disk:" || $1 == "pcie_nvme:" || $1 == "link:" || $1 == "aer:" { print; next }
        $1 == "disk" && $2 == "count:" { print; next }
        $1 == "pcie_nvme" && $2 == "count:" { print; next }
    ' | sort
}
machinecheck_fingerprint "$1"
'''


def _fingerprint(path: Path) -> str:
    result = subprocess.run(
        ["bash", "-c", FINGERPRINT_SNIPPET, "_", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def test_machinecheck_fingerprint_ignores_banners_and_keeps_inventory(tmp_path):
    before = tmp_path / "before.log"
    after_same = tmp_path / "after_same.log"
    after_changed = tmp_path / "after_changed.log"

    payload = textwrap.dedent(
        """\
        ----------------Machine Summary Message----------------
        cpu model name:                         Some CPU
        disk:                   		nvme0n1
        disk:                   		nvme1n1
        disk count:             		2
        pcie_nvme:              		0000:e1:00.0 Non-Volatile memory controller
        pcie_nvme count:        		1
        link:                   		0000:e1:00.0 LnkCap_Speed=16GT/s LnkCap_Width=x4 LnkSta_Speed=16GT/s LnkSta_Width=x4
        aer:                    		0000:e1:00.0 UESta=DLP- CESta=RxErr-
        Machinecheck finish
        """
    )
    before.write_text(payload, encoding="utf-8")
    after_same.write_text(
        payload.replace("Some CPU", "Other CPU").replace("Machine Summary", "CHANGED BANNER"),
        encoding="utf-8",
    )
    after_changed.write_text(
        payload.replace("LnkSta_Speed=16GT/s", "LnkSta_Speed=8GT/s"),
        encoding="utf-8",
    )

    assert _fingerprint(before) == _fingerprint(after_same)
    assert _fingerprint(before) != _fingerprint(after_changed)
    assert "cpu model" not in _fingerprint(before)
    assert "disk: nvme0n1" in _fingerprint(before)
    assert "link: 0000:e1:00.0" in _fingerprint(before)


def test_diff_sh_uses_whitelist_fingerprint():
    source = Path("IO_Stress/lib/diff.sh").read_text(encoding="utf-8")
    assert "machinecheck_fingerprint()" in source
    assert "Whitelist field differences" in source
    assert "diff -q $MachineCheckLog/info_before.log $MachineCheckLog/info_after.log" not in source
    assert "ERROR: Missing log files for MachineCheck diff comparison." in source
    assert "test_end 3" in source
    assert 'tee -a "$TestErrorLog/machine_diff_error.log" "$Result_Dir/result.log"' in source


def test_fio_all_skips_autologin_for_stress():
    source = Path("IO_Stress/Fio_All.sh").read_text(encoding="utf-8")
    assert "\nautologin\n" not in source
    assert "\nbackup\n" not in source
    assert "info_check" in source
