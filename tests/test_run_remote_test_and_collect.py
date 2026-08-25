from pathlib import Path


def test_remote_test_no_longer_gates_on_allow_destructive_fio():
    source = Path("ci/run_remote_test_and_collect.sh").read_text(encoding="utf-8")
    jenkinsfile = Path("Jenkinsfile").read_text(encoding="utf-8")

    assert "ALLOW_DESTRUCTIVE_FIO" not in source
    assert "ALLOW_DESTRUCTIVE_FIO" not in jenkinsfile
    assert "enable_failure_coredumps.sh" in source
    assert "ulimit -c unlimited" in source
    assert "python3 nvme_raid_test.py" in source
    assert "TEST_IDLE_TIMEOUT_MINUTES=${TEST_IDLE_TIMEOUT_MINUTES}" in source
