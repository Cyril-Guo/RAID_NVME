from pathlib import Path


FIO_LIB_FILES = (
    "IO_Stress/lib/fio.sh",
    "IO_Stress/lib/fio_powercycle.sh",
    "IO_Stress/lib/fio_verify.sh",
)


def fio_lib_source():
    return "\n".join(Path(name).read_text(encoding="utf-8") for name in FIO_LIB_FILES)


def test_powercycle_captures_per_loop_and_summary_dmesg():
    fio = fio_lib_source()
    direct = Path("IO_Stress/powercycle_direct.sh").read_text(encoding="utf-8")
    resume = Path("IO_Stress/run_fio.sh").read_text(encoding="utf-8")

    assert "collect_powercycle_dmesg()" in fio
    assert "update_dmesg_summary()" in fio
    assert "fio_powercycle.sh" in Path("IO_Stress/lib/fio.sh").read_text(encoding="utf-8")
    assert "dmesg_loop_${loop_id}.log" in fio
    assert "dmesg_summary.log" in fio
    assert "===== dmesg loop ${loop_id} =====" in fio
    assert "dmesg -c" not in fio

    assert "collect_powercycle_dmesg" in direct
    assert "collect_powercycle_dmesg" in resume
    assert "do_fio" in direct
    assert "skip do_fio" not in direct
    assert "do_fio" in resume
    assert "skip do_fio" not in resume
