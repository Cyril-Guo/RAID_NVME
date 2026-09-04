import os
import subprocess
from pathlib import Path

import pytest

import nvme_raid_test


def test_powercycle_selection_must_run_alone():
    nvme_raid_test.validate_powercycle_selection(["reboot"])
    with pytest.raises(ValueError, match="must run alone"):
        nvme_raid_test.validate_powercycle_selection(["reboot", "basic_io"])
    with pytest.raises(ValueError, match="must run alone"):
        nvme_raid_test.validate_powercycle_selection(["dc", "mix"])


def test_qemu_vfio_protection_walks_all_block_parents():
    source = Path("ci/qemu_vm_prepare.sh").read_text(encoding="utf-8")
    assert "parent[$1]=$2" in source
    assert "while (changed)" in source
    assert "keep system NVMe on host" in source


def test_fio_failure_and_cleanup_are_propagated():
    source = Path("IO_Stress/lib/fio.sh").read_text(encoding="utf-8")
    runner = Path("IO_Stress/run_fio.sh").read_text(encoding="utf-8")
    direct = Path("IO_Stress/powercycle_direct.sh").read_text(encoding="utf-8")
    assert 'local rc="${1:-0}"' in source
    assert 'exit "$rc"' in source
    assert 'run_single "$a" || return $?' in source
    assert 'run_all "$b" || return $?' in source
    assert 'run_suball "$b" || return $?' in source
    assert "kill -TERM \"-${victim_pid}\"" in source
    assert 'test_end "$fio_rc"' in runner
    assert 'test_end "$fio_rc"' in direct


def test_watchdogs_track_only_fio_targets():
    local_source = Path("IO_Stress/lib/fio.sh").read_text(encoding="utf-8")
    outer_source = Path("ci/io_progress_signature.sh").read_text(encoding="utf-8")
    assert 'fio_io_progress_signature "$configuration"' in local_source
    assert "filename[[:space:]]*=" in local_source
    assert "active_fio_devices" in outer_source
    assert "pgrep -x fio" in outer_source
    assert "^dp[0-9]+-vd[0-9]+$" in outer_source


def test_filesystem_partition_refresh_uses_partx_and_count_validation():
    source = Path("IO_Stress/lib/fio.sh").read_text(encoding="utf-8")
    assert "refresh_partition_devices" in source
    assert 'partx -a "$device"' in source
    assert "actual_partition_count != FILESYSTEM_PARTITIONS_PER_DISK" in source
    assert "lsblk -lnpo NAME,TYPE" in source


def test_runner_cleans_detached_remote_fio_and_waits_powercycle():
    source = Path("ci/run_remote_test_and_collect.sh").read_text(encoding="utf-8")
    wait_source = Path("ci/wait_powercycle_completion.sh").read_text(encoding="utf-8")
    assert "cancel_remote_test" in source
    assert "pkill -TERM -x fio" in source
    assert "wait_powercycle_completion.sh" in source
    assert "all power-cycle loops completed" in wait_source
    assert "item_failed" in wait_source


def test_powercycle_wait_accepts_completed_remote_log(tmp_path):
    items = tmp_path / "items.ini"
    items.write_text(
        "[selection]\nreboot=yes\ndc=no\n[reboot]\nFIO_CYCLES=1\n",
        encoding="utf-8",
    )
    result_dir = tmp_path / "remote" / "IO_Stress" / "log" / "ResultLog"
    result_dir.mkdir(parents=True)
    (result_dir / "reboot_command.log").write_text(
        "[REBOOT] request start\n[POWER] all power-cycle loops completed\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.update(
        {
            "NODE_IP": "test-node",
            "REMOTE_DIR": (tmp_path / "remote").as_posix(),
            "REMOTE_SSH_COMMAND": "bash -c",
            "TEST_ITEMS_FILE": items.as_posix(),
            "POWER_CYCLE_POLL_SECONDS": "1",
        }
    )

    completed = subprocess.run(
        ["bash", "ci/wait_powercycle_completion.sh"],
        cwd=Path.cwd(),
        env=env,
        text=True,
        capture_output=True,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    assert "already completed" in completed.stdout


def test_jenkins_serializes_each_dut_and_bounds_feishu():
    source = Path("Jenkinsfile").read_text(encoding="utf-8")
    assert "def dutLockResource(ip)" in source
    assert source.count("lock(resource: dutLockResource(ip))") >= 2
    assert "--connect-timeout 10 --max-time 30 --retry 2" in source
    assert "Feishu notification failed with exit code" in source


def test_invalid_fio_arguments_exit_nonzero():
    source = Path("IO_Stress/lib/arguments.sh").read_text(encoding="utf-8")
    check_block = source.split("function check_arguments()", 1)[1]
    assert "isn't a number,exit" in check_block
    assert "exit 1" in check_block
    assert "the DC mode isn't supported" in check_block
