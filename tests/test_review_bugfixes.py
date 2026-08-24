from pathlib import Path


def test_fio_all_skips_autologin_for_stress_paths():
    source = Path("IO_Stress/Fio_All.sh").read_text(encoding="utf-8")

    assert "\nautologin\n" not in source
    assert "must not rewrite" in source
    assert "info_check" in source
    assert "fio_cycle" in source


def test_allow_destructive_fio_defaults_to_one():
    remote = Path("ci/run_remote_test_and_collect.sh").read_text(encoding="utf-8")
    physical = Path("ci/run_physical_host_test.sh").read_text(encoding="utf-8")

    assert 'ALLOW_DESTRUCTIVE_FIO:-1' in remote or 'ALLOW_DESTRUCTIVE_FIO:-1}' in remote
    assert "${ALLOW_DESTRUCTIVE_FIO:-1}" in remote or 'allow_fio="${ALLOW_DESTRUCTIVE_FIO:-1}"' in remote
    assert 'ALLOW_DESTRUCTIVE_FIO="${ALLOW_DESTRUCTIVE_FIO:-1}"' in physical
    assert "ALLOW_DESTRUCTIVE_FIO:-YES" not in remote
    assert "ALLOW_DESTRUCTIVE_FIO:-YES" not in physical


def test_smart_error_log_is_defined_and_created():
    variables = Path("IO_Stress/lib/global_variable.sh").read_text(encoding="utf-8")
    init = Path("IO_Stress/lib/init.sh").read_text(encoding="utf-8")

    assert "SmartErrorLog=$RawLog/SmartErrorLog" in variables
    assert "mkdir -p $SmartErrorLog/CheckNoStop" in init
    assert "SmartErrorLog/CheckNoStop" in init
