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
