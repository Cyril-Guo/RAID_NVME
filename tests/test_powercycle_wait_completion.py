from pathlib import Path


def test_wait_powercycle_completion_script_exists_and_checks_markers():
    source = Path("ci/wait_powercycle_completion.sh").read_text(encoding="utf-8")
    assert "BEGIN SELECTION" in source
    assert "all power-cycle loops completed" in source
    assert "Power-cycle test completed all" in source
    assert "request start" in source
    assert "POWER_CYCLE_COMPLETION_TIMEOUT_MINUTES" in source
    assert "is_powercycle_item" in source
    assert "item_short_name" in source
    assert "powercycle_log_name" in source
    assert "test_ci_" in source
    assert "selected_run_keys+=" in source
    assert '"${REMOTE_DIR}/cases/${run_key}/${RESULT_REL}"' in source


def test_powercycle_direct_extends_reboot_grace_for_clean_ssh_exit():
    source = Path("IO_Stress/powercycle_direct.sh").read_text(encoding="utf-8")
    assert 'POWER_CYCLE_COMMAND_GRACE="${POWER_CYCLE_COMMAND_GRACE:-90}"' in source


