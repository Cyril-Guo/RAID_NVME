from test_items.fio_run import collect_failure_lines as lawdisk_failures
from test_items.fio_run import collect_failure_lines as filesystem_failures
from test_items.fio_run import collect_failure_lines as mix_failures


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


def test_collect_failure_lines_ignores_partial_disk_fio_errors_when_script_ok():
    sample = """
    [FIO] finish model=randwrite bs=4k qd=64 runtime=30s (#1) config=1-randwrite-4k-64-30.log rc=4 elapsed=30s(30s) planned_runtime=30s
    [FIO] partial disk failure recorded, model=randwrite bs=4k qd=64 runtime=30s (#1) config=1-randwrite-4k-64-30.log rc=4 elapsed=30s(30s); at least one disk had IO, continue
    ----- FIO error detail begin (log=1.txt model=randwrite rc=4) -----
    fio: io_u error on file /dev/dp0-vd2: Input/output error
    err=5/file:io_u.c:1845, func=io_u error, error=Input/output error
    ----- FIO error detail end (lines=2) -----
    [FIO] MIX job 1 recorded FIO/disk errors rc=4/0/0/0 disks=dp8-vd2; MIX_FAIL_ON_ANY=no, continue
    """

    ignored = mix_failures(sample, ignore_fio_job_errors=True)
    assert ignored == []
    assert lawdisk_failures(sample, ignore_fio_job_errors=True) == []
    assert filesystem_failures(sample, ignore_fio_job_errors=True) == []

    kept = mix_failures(sample)
    assert any("io_u error" in line for line in kept)
    assert any("FIO error detail begin" in line for line in kept)


def test_collect_failure_lines_still_keeps_guard_failures_when_ignoring_fio_job_errors():
    sample = """
    Fail to detect system disk. Refuse to run to avoid any IO on OS disk. Exit.
    fio: io_u error on file /dev/dp0-vd2: Invalid argument
    """

    lines = lawdisk_failures(sample, ignore_fio_job_errors=True)
    assert lines == [
        "Fail to detect system disk. Refuse to run to avoid any IO on OS disk. Exit.",
    ]
    assert filesystem_failures(sample, ignore_fio_job_errors=True) == lines
    assert mix_failures(sample, ignore_fio_job_errors=True) == lines
