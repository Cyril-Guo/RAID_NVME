from pathlib import Path


def test_fio_runner_only_iterates_generated_log_configs():
    source = Path("IO_Stress/lib/fio.sh").read_text(encoding="utf-8")

    assert "grep '\\.log$'" in source
    assert "for configuration in `ls -p $Config_Dir | grep -v / | sort" not in source
