from test_items.test_smoke_03_lawdisk import _collect_failure_lines as lawdisk_failures
from test_items.test_smoke_04_filesystem import _collect_failure_lines as filesystem_failures
from test_items.test_smoke_05_mix import _collect_failure_lines as mix_failures


def test_collect_failure_lines_matches_fio_errors():
    sample = """
    Job 2/4 is Running..
    FIO command failed, config 2-randwrite-4k-32-300.log, rc=8
    more logs...
    """

    assert filesystem_failures(sample) == ["FIO command failed, config 2-randwrite-4k-32-300.log, rc=8"]
    assert lawdisk_failures(sample) == ["FIO command failed, config 2-randwrite-4k-32-300.log, rc=8"]
    assert mix_failures(sample) == ["FIO command failed, config 2-randwrite-4k-32-300.log, rc=8"]


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
    ReadIOPs=92.7k
    PASSED
    """

    assert filesystem_failures(sample) == []
    assert lawdisk_failures(sample) == []
    assert mix_failures(sample) == []
