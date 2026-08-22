from pathlib import Path


FIO_LIB_FILES = (
    "IO_Stress/lib/fio.sh",
    "IO_Stress/lib/fio_powercycle.sh",
    "IO_Stress/lib/fio_verify.sh",
)


def fio_lib_source():
    return "\n".join(Path(name).read_text(encoding="utf-8") for name in FIO_LIB_FILES)


def test_powercycle_completion_has_success_path():
    fio_source = fio_lib_source()
    run_source = Path("IO_Stress/run_fio.sh").read_text(encoding="utf-8")

    assert "all power-cycle loops completed" in fio_source
    assert "return 2" in fio_source
    assert "reboot_rc -eq 2" in run_source
    assert "Power-cycle test completed all $LOOP loops." in run_source
    assert "test_end" in run_source
    assert "local rc=${1:-0}" in fio_source
    assert 'exit "${rc}"' in fio_source
