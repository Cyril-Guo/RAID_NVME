from test_items.test_smoke_03_lawdisk import _collect_failure_lines as lawdisk_failures
from test_items.test_smoke_04_filesystem import _collect_failure_lines as filesystem_failures
from test_items.test_smoke_05_mix import _collect_failure_lines as mix_failures


def test_collect_failure_lines_matches_fio_errors():
    sample = """
    Job 2/4 is Running..
    FIO command failed, model=randwrite bs=4k qd=64 runtime=30s (#2), config=2-randwrite-4k-64-30.log, elapsed=12s(12s), planned_runtime=30s, rc=8
    more logs...
    """

    expected = [
        "FIO command failed, model=randwrite bs=4k qd=64 runtime=30s (#2), "
        "config=2-randwrite-4k-64-30.log, elapsed=12s(12s), planned_runtime=30s, rc=8"
    ]
    assert filesystem_failures(sample) == expected
    assert lawdisk_failures(sample) == expected
    assert mix_failures(sample) == expected


def test_collect_failure_lines_matches_fio_guard_failures():
    sample = """
    Fail to detect system disk. Refuse to run to avoid any IO on OS disk. Exit.
    FIO failed: system disk not detected
    """

    assert lawdisk_failures(sample) == [
        "Fail to detect system disk. Refuse to run to avoid any IO on OS disk. Exit.",
        "FIO failed: system disk not detected",
    ]
    assert filesystem_failures(sample) == lawdisk_failures(sample)
    assert mix_failures(sample) == lawdisk_failures(sample)


def test_collect_failure_lines_ignores_normal_output():
    sample = """
    Job 1/4 is Running..
    [FIO] start model=randread bs=4k qd=64 runtime=30s (#1) config=1-randread-4k-64-30.log planned_runtime=30s idle_watchdog=900s
    ReadIOPs=92.7k
    PASSED
    """

    assert filesystem_failures(sample) == []
    assert lawdisk_failures(sample) == []
    assert mix_failures(sample) == []


def test_collect_failure_lines_includes_fio_error_detail_block():
    sample = """
    FIO command failed, model=rw, bs=1k, qd=32, runtime=30s, config=config-1-rw-1k-32-30.log, elapsed=30s(30s), planned_runtime=30s, rc=8
    ----- FIO error detail begin (log=config-1-rw-1k-32-30.log model=rw rc=8) -----
    fio: io_u error on file /dev/dp0-vd1: Invalid argument: read offset=0, buflen=1024
    fio: first direct IO errored. File system may not support direct IO, or iomem_align= is bad, or invalid block size. Try setting direct=0.
    err=22/file:io_u.c:1845, func=io_u error, error=Invalid argument
    ----- FIO error detail end (lines=3) -----
    """

    lines = mix_failures(sample)
    assert any("FIO command failed" in line for line in lines)
    assert any("io_u error" in line for line in lines)
    assert any("Invalid argument" in line for line in lines)
    assert any("FIO error detail begin" in line for line in lines)
    assert any("FIO error detail end" in line for line in lines)
    assert lawdisk_failures(sample) == lines
    assert filesystem_failures(sample) == lines


def test_collect_failure_lines_records_machinecheck_unless_ignored():
    sample = """
    ERROR: MachineCheck inconsistencies found at loop 0. Check machine_diff_error.log for details.
    Whitelist field differences detected between MachineCheck before/after logs.
    FIO command failed, model=randwrite bs=4k qd=64 runtime=30s (#2), config=2-randwrite-4k-64-30.log, elapsed=12s(12s), planned_runtime=30s, rc=8
    """

    mc_and_fio = lawdisk_failures(sample)
    assert any("MachineCheck inconsistencies found" in line for line in mc_and_fio)
    assert any("FIO command failed" in line for line in mc_and_fio)

    fio_only = lawdisk_failures(sample, ignore_machinecheck=True)
    assert fio_only == [
        "FIO command failed, model=randwrite bs=4k qd=64 runtime=30s (#2), "
        "config=2-randwrite-4k-64-30.log, elapsed=12s(12s), planned_runtime=30s, rc=8"
    ]
    assert filesystem_failures(sample, ignore_machinecheck=True) == fio_only
    assert mix_failures(sample, ignore_machinecheck=True) == fio_only
