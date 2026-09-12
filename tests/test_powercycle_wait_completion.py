from pathlib import Path


def test_ci_branch_has_no_powercycle_wait_script():
    """CI has no reboot/dc cases; completion wait belongs on PowerCycle only."""
    assert not Path("ci/wait_powercycle_completion.sh").exists()


def test_powercycle_direct_extends_reboot_grace_for_clean_ssh_exit():
    source = Path("IO_Stress/powercycle_direct.sh").read_text(encoding="utf-8")
    assert (
        'POWER_CYCLE_COMMAND_GRACE="${POWER_CYCLE_COMMAND_GRACE:-90}"'
        in source
    )
