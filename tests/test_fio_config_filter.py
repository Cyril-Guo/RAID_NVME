from pathlib import Path
import csv
import os
import subprocess
import textwrap


FIO_LIB_FILES = (
    "IO_Stress/lib/fio.sh",
    "IO_Stress/lib/fio_powercycle.sh",
    "IO_Stress/lib/fio_verify.sh",
)


def fio_lib_source():
    return "\n".join(Path(name).read_text(encoding="utf-8") for name in FIO_LIB_FILES)


def test_fio_runner_only_iterates_generated_log_configs():
    source = fio_lib_source()

    assert "grep '\\.log$'" in source
    assert "for configuration in `ls -p $Config_Dir | grep -v / | sort" not in source


def test_ci_filesystem_profile_is_random_mixed_aligned_and_unaligned_io():
    with Path("IO_Stress/Input_Config_filesystem.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        rows = list(csv.reader(handle))

    assert len(rows) == 3
    block_sizes, random_pct, read_pct, iodepth, runtime, numjobs, offset = rows[1]
    assert block_sizes.startswith("bssplit=")
    assert "512/4" in block_sizes
    assert "513/4" in block_sizes
    assert "16777215/4" in block_sizes
    assert "16m/4" in block_sizes
    assert random_pct == "100"
    assert read_pct == "50"
    assert iodepth == "32"
    assert runtime == "180"
    assert numjobs == "1"
    assert offset == "0"

    def size_bytes(value):
        suffixes = {"k": 1024, "m": 1024 * 1024}
        suffix = value[-1].lower()
        if suffix in suffixes:
            return int(value[:-1]) * suffixes[suffix]
        return int(value)

    weighted_sizes = []
    for entry in block_sizes.removeprefix("bssplit=").split(":"):
        size, weight = entry.split("/")
        weighted_sizes.append((size_bytes(size), int(weight)))

    assert min(size for size, _ in weighted_sizes) == 512
    assert max(size for size, _ in weighted_sizes) == 16 * 1024 * 1024
    assert sum(weight for _, weight in weighted_sizes) == 100
    assert sum(weight for size, weight in weighted_sizes if size % 512 == 0) == 50
    assert sum(weight for size, weight in weighted_sizes if size % 512 != 0) == 50


def test_ci_filesystem_prepares_sixteen_partitions_and_buffered_async_io():
    source = Path("IO_Stress/lib/fio.sh").read_text(encoding="utf-8")

    assert "FILESYSTEM_PARTITIONS_PER_DISK=16" in source
    assert "actual_partition_count != FILESYSTEM_PARTITIONS_PER_DISK" in source
    assert "refresh_partition_devices" in source
    assert 'partx -a "$device"' in source
    model_block = source.split("FILESYSTEM_MODEL_SIZE_PAIRS=(", 1)[1].split(")", 1)[0]
    models = [line.strip().strip('"') for line in model_block.splitlines() if ":" in line]
    assert len(models) == 16
    assert len(set(models)) == 16
    assert models[0] == "512:513"
    assert models[-1] == "16m:16777215"
    assert 'for model_index in "${!FILESYSTEM_MODEL_SIZE_PAIRS[@]}"' in source
    assert 'echo "numjobs=1"' in source
    assert 'echo "iodepth=32"' in source
    assert 'echo "rw=randrw"' in source
    assert 'echo "rwmixread=$read_percentage"' in source
    assert "FILESYSTEM_MODEL_RUNTIME=180" in source
    assert "ioengine=io_uring" in source
    assert "direct=0" in source
    assert "bs_unaligned=1" in source


def test_filesystem_partition_refresh_runs_partx_after_successful_partprobe(tmp_path):
    call_log = (tmp_path / "calls.log").as_posix()
    for command in ("partprobe", "partx", "udevadm"):
        executable = tmp_path / command
        executable.write_text(
            textwrap.dedent(
                f"""\
                #!/bin/sh
                printf '{command} %s\\n' "$*" >> "$CALL_LOG"
                exit 0
                """
            ),
            encoding="utf-8",
        )
        executable.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{tmp_path}{os.pathsep}{env['PATH']}"
    env["CALL_LOG"] = call_log
    result = subprocess.run(
        [
            "bash",
            "-c",
            "source IO_Stress/lib/fio.sh; refresh_partition_devices /dev/dp0-vd1",
        ],
        cwd=Path.cwd(),
        env=env,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    calls = Path(call_log).read_text(encoding="utf-8").splitlines()
    assert calls == [
        "partprobe /dev/dp0-vd1",
        "partx -a /dev/dp0-vd1",
        "udevadm settle --timeout=30",
    ]


def test_ci_filesystem_runtime_can_be_overridden_from_test_items():
    source = Path("IO_Stress/lib/fio.sh").read_text(encoding="utf-8")
    config = Path("test_items.txt").read_text(encoding="utf-8")

    assert "configure_filesystem_rounds" in source
    assert 'total_runtime="${FIO_RUNTIME:-$FILESYSTEM_MODEL_RUNTIME}"' in source
    assert "FIO_RUNTIME" in config


def test_ci_filesystem_appends_sixteen_distinct_fio_jobs(tmp_path):
    first_config_path = (tmp_path / "round1.log").as_posix()
    second_config_path = (tmp_path / "round2.log").as_posix()
    result = subprocess.run(
        [
            "bash",
            "-lc",
            "source IO_Stress/lib/fio.sh; "
            f"Cur_Dir='{tmp_path.as_posix()}'; "
            f": > '{first_config_path}'; : > '{second_config_path}'; "
            f"append_filesystem_model_jobs /tmp/fio.data testp1 '{first_config_path}' 1; "
            f"append_filesystem_model_jobs /tmp/fio.data testp1 '{second_config_path}' 2",
        ],
        cwd=Path.cwd(),
        check=True,
        text=True,
        capture_output=True,
    )

    assert result.stderr == ""
    first_content = Path(first_config_path).read_text(encoding="utf-8")
    second_content = Path(second_config_path).read_text(encoding="utf-8")
    first_sections = [line for line in first_content.splitlines() if line.startswith("[")]
    first_bssplits = [line for line in first_content.splitlines() if line.startswith("bssplit=")]
    second_bssplits = [line for line in second_content.splitlines() if line.startswith("bssplit=")]
    first_read_mix = [line for line in first_content.splitlines() if line.startswith("rwmixread=")]
    second_read_mix = [line for line in second_content.splitlines() if line.startswith("rwmixread=")]

    assert first_sections == [
        f"[testp1-round-0001-model-{index:02d}]" for index in range(1, 17)
    ]
    assert len(first_bssplits) == 16
    assert len(set(first_bssplits)) == 16
    assert first_bssplits != second_bssplits
    assert first_read_mix != second_read_mix
    assert first_content.count("rw=randrw") == 16
    assert first_content.count("iodepth=32") == 16
    assert first_content.count("numjobs=1") == 16


def test_ci_filesystem_generates_one_changed_model_set_per_three_minutes(tmp_path):
    config_dir = (tmp_path / "jobs").as_posix()
    result = subprocess.run(
        [
            "bash",
            "-lc",
            "source IO_Stress/lib/fio.sh; "
            f"Config_Dir='{config_dir}'; mkdir -p \"$Config_Dir\"; "
            "add_file=(/tmp/fiotest/testp1/fio.data); "
            "FIO_RUNTIME=540; log_interval=100; configure_filesystem_rounds",
        ],
        cwd=Path.cwd(),
        check=True,
        text=True,
        capture_output=True,
    )

    assert "3 rounds x 180s = 540s" in result.stdout
    configs = sorted((tmp_path / "jobs").glob("*.log"))
    assert [path.name for path in configs] == [
        "0001-filesystem-models-32-180.log",
        "0002-filesystem-models-32-180.log",
        "0003-filesystem-models-32-180.log",
    ]
    contents = [path.read_text(encoding="utf-8") for path in configs]
    assert all(content.count("runtime=180") == 1 for content in contents)
    assert all(content.count("round-") == 16 for content in contents)
    assert len(set(contents)) == 3


def test_fio_system_disk_detection_handles_lvm_parent_disk():
    source = fio_lib_source()

    assert "normalize_system_disk" in source
    assert "lsblk -nr -o NAME,PKNAME,MOUNTPOINT" in source
    assert "findmnt -nvo SOURCE" in source
    assert "extract_parent_disk" in source
    assert "BASH_REMATCH[1]" in source


def test_fio_auto_disk_selection_prefers_draid_virtual_disks():
    source = fio_lib_source()

    assert "select_auto_test_disks" in source
    assert "grep -E '^dp[0-9]+-vd[0-9]+$'" in source
    assert "specified_disk_contains_system" in source
    assert "validate_test_disks" in source
    assert "assert_not_system_disk" in source
    assert "collect_system_block_devices" in source
    assert "device_has_mountpoint" in source


def test_fio_runs_under_watchdog_timeout():
    source = fio_lib_source()

    assert "run_fio_with_watchdog" in source
    assert "fio_idle_timeout_seconds" in source
    assert "fio_io_progress_signature" in source
    assert "TEST_IDLE_TIMEOUT_MINUTES" in source
    assert "FIO_IDLE_TIMEOUT_SECONDS" in source
    assert "idle watchdog timeout after" in source
    assert "without output or non-system disk IO progress" in source
    assert 'timeout --kill-after=60s "${timeout_seconds}s" fio' not in source
    assert "FIO command failed in MIX mode" in source
    assert "fio_output_has_successful_io" in source
    assert "mix_fail_on_any_enabled" in source
    assert "fio_error_disks" in source
    assert "MIX_FAIL_ON_ANY=yes, fail" in source
    assert "MIX_FAIL_ON_ANY=no, continue" in source
    assert "IOPS=0 is not a failure" in source
    assert "any disk IO error fails (non-MIX)" in source
    assert "partial disk failure recorded" not in source
    assert "at least one disk had IO, continue" not in source
    assert "all disks failed for config" in source
    assert source.count("run_fio_with_watchdog") >= 6
    assert 'watch_interval_seconds="${FIO_WATCH_INTERVAL_SECONDS:-1}"' in source
    assert "if ! kill -0 \"$fio_pid\" 2>/dev/null; then" in source
    assert "append_fio_error_detail" in source
    assert "----- FIO error detail begin" in source
    assert "io_u error" in source


def test_verify_jobs_replace_full_disk_size_with_slice_size():
    source = Path("IO_Stress/lib/fio_verify.sh").read_text(encoding="utf-8")

    assert 'sed -i "s#^size=100%\\$#size=${io_size}#"' in source


def test_powercycle_verify_jobs_enable_serialize_overlap():
    verify_source = Path("IO_Stress/lib/fio_verify.sh").read_text(encoding="utf-8")
    fio_source = Path("IO_Stress/lib/fio.sh").read_text(encoding="utf-8")

    assert "serialize_overlap=1" in verify_source
    assert "fio_verify_strip_config_directives" in fio_source
    assert '/serialize_overlap/d' in verify_source


def test_mix_io_generates_random_mixio_jobs():
    source = fio_lib_source()

    assert "python3 $Cur_Dir/random_choice.py" in source
    assert "mv random_choice.csv MixIO$i.csv" in source
    assert 'cp "$Cur_Dir/$filename" "MixIO${i}.csv"' not in source


def test_fio_cycle_propagates_run_fio_exit_code():
    source = fio_lib_source()
    cycle = source.split("function fio_cycle()", 1)[1]

    assert "sh run_fio.sh" in cycle
    assert "exit $?" in cycle


def test_io_stress_does_not_clear_system_logs():
    source = Path("IO_Stress/lib/init.sh").read_text(encoding="utf-8")

    assert "dmesg -c" not in source
    assert "ipmitool sel clear" not in source
    assert "echo \"\" > $messages_log" not in source
    assert "echo \"\" > $dmesg_log" not in source


def test_fio_system_disk_detection_resolves_lvm_to_nvme_parent(tmp_path):
    findmnt = tmp_path / "findmnt"
    findmnt.write_text(
        textwrap.dedent(
            """\
            #!/bin/sh
            if [ "$1" = "-nvo" ] && [ "$2" = "SOURCE" ]; then
              case "$3" in
                /) echo /dev/mapper/ubuntu--vg-ubuntu--lv ;;
                /boot) echo /dev/mapper/ubuntu--vg-lv--0 ;;
                /boot/efi) echo /dev/nvme3n1p1 ;;
              esac
            fi
            """
        ),
        encoding="utf-8",
    )
    lsblk = tmp_path / "lsblk"
    lsblk.write_text(
        textwrap.dedent(
            """\
            #!/bin/sh
            if [ "$1" = "-nr" ] && [ "$2" = "-o" ] && [ "$3" = "NAME,PKNAME,MOUNTPOINT" ]; then
              echo "nvme3n1  "
              echo "nvme3n1p1 nvme3n1 /boot/efi"
              echo "nvme3n1p2 nvme3n1 "
              echo "nvme3n1p3 nvme3n1 "
              echo "ubuntu--vg-ubuntu--lv nvme3n1p3 /"
              echo "ubuntu--vg-lv--0 nvme3n1p3 /boot"
              echo "sdc  "
              echo "sdc1 sdc /mnt/data"
            elif [ "$1" = "-nr" ] && [ "$2" = "-o" ] && [ "$3" = "NAME,PKNAME" ]; then
              echo "ubuntu--vg-ubuntu--lv nvme3n1p3"
              echo "ubuntu--vg-lv--0 nvme3n1p3"
              echo "nvme3n1p1 nvme3n1"
              echo "nvme3n1p2 nvme3n1"
              echo "nvme3n1p3 nvme3n1"
            elif [ "$1" = "-dn" ]; then
              echo "dp0-vd1 disk"
              echo "dp0-vd2 disk"
              echo "nvme3n1 disk"
            fi
            """
        ),
        encoding="utf-8",
    )
    findmnt.chmod(0o755)
    lsblk.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{tmp_path}{os.pathsep}{env['PATH']}"
    result = subprocess.run(
        [
            "bash",
            "-lc",
            "set -e; "
            "source IO_Stress/lib/fio.sh; "
            "get_system_disk; "
            "echo system_disk=$system_disk; "
            "echo system_block_devices=$system_block_devices; "
            "disk=$(select_auto_test_disks); "
            "echo auto_disks=$(echo $disk | tr ' ' ','); "
            "specified_disk=nvme3n1p1; "
            "specified_disk_contains_system && echo specified_partition_rejected=yes; "
            "test_disk=dp0-vd1,nvme3n1p1; "
            "validate_test_disks || echo validate_partition_rejected=yes; "
            "disk_is_system ubuntu--vg-ubuntu--lv && echo lvm_is_system=yes; "
            "disk_is_system nvme3n1p3 && echo partition_is_system=yes; "
            "system_disk=sda; "
            "system_block_devices='sda sda1 sda2'; "
            "disk_is_system sda2 && echo sata_partition_is_system=yes; "
            "assert_not_system_disk sdc 'run fio' || echo mounted_disk_rejected=yes",
        ],
        cwd=Path.cwd(),
        env=env,
        check=True,
        text=True,
        capture_output=True,
    )

    assert "system_disk=nvme3n1" in result.stdout
    assert "nvme3n1p1" in result.stdout
    assert "nvme3n1p3" in result.stdout
    assert "ubuntu--vg-ubuntu--lv" in result.stdout
    assert "auto_disks=dp0-vd1,dp0-vd2" in result.stdout
    assert "specified_partition_rejected=yes" in result.stdout
    assert "validate_partition_rejected=yes" in result.stdout
    assert "lvm_is_system=yes" in result.stdout
    assert "partition_is_system=yes" in result.stdout
    assert "sata_partition_is_system=yes" in result.stdout
    assert "mounted_disk_rejected=yes" in result.stdout


def test_fio_system_disk_detection_falls_back_to_boot_nvme_partition(tmp_path):
    findmnt = tmp_path / "findmnt"
    findmnt.write_text(
        textwrap.dedent(
            """\
            #!/bin/sh
            if [ "$1" = "-nvo" ] && [ "$2" = "SOURCE" ]; then
              case "$3" in
                /) echo /dev/mapper/ubuntu--vg-ubuntu--lv ;;
                /boot) echo /dev/nvme3n1p2 ;;
                /boot/efi) echo /dev/nvme3n1p1 ;;
              esac
            fi
            """
        ),
        encoding="utf-8",
    )
    lsblk = tmp_path / "lsblk"
    lsblk.write_text(
        textwrap.dedent(
            """\
            #!/bin/sh
            if [ "$1" = "-nr" ] && [ "$2" = "-o" ] && [ "$3" = "NAME,PKNAME,MOUNTPOINT" ]; then
              echo "ubuntu--vg-ubuntu--lv  /"
              echo "nvme3n1p2  /boot"
              echo "nvme3n1p1  /boot/efi"
            elif [ "$1" = "-nr" ] && [ "$2" = "-o" ] && [ "$3" = "NAME,PKNAME" ]; then
              echo "ubuntu--vg-ubuntu--lv "
              echo "nvme3n1p2 "
              echo "nvme3n1p1 "
            elif [ "$1" = "-dn" ]; then
              echo "dp0-vd1 disk"
            fi
            """
        ),
        encoding="utf-8",
    )
    findmnt.chmod(0o755)
    lsblk.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{tmp_path}{os.pathsep}{env['PATH']}"
    result = subprocess.run(
        [
            "bash",
            "-lc",
            "source IO_Stress/lib/fio.sh; "
            "get_system_disk; "
            "echo system_disk=$system_disk; "
            "echo system_sources=$system_disk_sources; "
            "disk=$(select_auto_test_disks); "
            "echo auto_disks=$(echo $disk | tr ' ' ',')",
        ],
        cwd=Path.cwd(),
        env=env,
        check=True,
        text=True,
        capture_output=True,
    )

    assert "system_disk=nvme3n1" in result.stdout
    assert "/dev/nvme3n1p2" in result.stdout
    assert "/dev/nvme3n1p1" in result.stdout
    assert "auto_disks=dp0-vd1" in result.stdout


def test_fio_system_disk_detection_handles_virtio_vda_partitions(tmp_path):
    findmnt = tmp_path / "findmnt"
    findmnt.write_text(
        textwrap.dedent(
            """\
            #!/bin/sh
            if [ "$1" = "-nvo" ] && [ "$2" = "SOURCE" ]; then
              case "$3" in
                /) echo /dev/vda1 ;;
                /boot) echo /dev/vda15 ;;
                /boot/efi) echo /dev/vda15 ;;
              esac
            fi
            """
        ),
        encoding="utf-8",
    )
    lsblk = tmp_path / "lsblk"
    lsblk.write_text(
        textwrap.dedent(
            """\
            #!/bin/sh
            if [ "$1" = "-nr" ] && [ "$2" = "-o" ] && [ "$3" = "NAME,PKNAME,MOUNTPOINT" ]; then
              echo "vda  "
              echo "vda1 vda /"
              echo "vda15 vda /boot/efi"
              echo "dp0-vd1  "
            elif [ "$1" = "-nr" ] && [ "$2" = "-o" ] && [ "$3" = "NAME,PKNAME" ]; then
              echo "vda1 vda"
              echo "vda15 vda"
            elif [ "$1" = "-dn" ]; then
              echo "vda disk"
              echo "dp0-vd1 disk"
            fi
            """
        ),
        encoding="utf-8",
    )
    findmnt.chmod(0o755)
    lsblk.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{tmp_path}{os.pathsep}{env['PATH']}"
    result = subprocess.run(
        [
            "bash",
            "-lc",
            "set -e; "
            "source IO_Stress/lib/fio.sh; "
            "get_system_disk; "
            "echo system_disk=$system_disk; "
            "echo system_block_devices=$system_block_devices; "
            "disk_is_system vda15 && echo vda15_is_system=yes; "
            "test_disk=dp0-vd1,vda15; "
            "validate_test_disks || echo validate_vda_partition_rejected=yes; "
            "disk=$(select_auto_test_disks); "
            "echo auto_disks=$(echo $disk | tr ' ' ',')",
        ],
        cwd=Path.cwd(),
        env=env,
        check=True,
        text=True,
        capture_output=True,
    )

    assert "system_disk=vda" in result.stdout
    assert "vda15_is_system=yes" in result.stdout
    assert "validate_vda_partition_rejected=yes" in result.stdout
    assert "auto_disks=dp0-vd1" in result.stdout


def test_fio_system_disk_detection_parses_jenkins_source_line_under_set_e():
    result = subprocess.run(
        [
            "bash",
            "-lc",
            "set -e; "
            "source IO_Stress/lib/fio.sh; "
            "devices='/dev/mapper/ubuntu--vg-ubuntu--lv /dev/nvme3n1p2 /dev/nvme3n1p1 nvme3n1p1 nvme3n1 nvme3n1p2 nvme3n1 ubuntu--vg-ubuntu--lv nvme3n1p3'; "
            "extract_parent_disks_from_words $devices | awk 'NF && !seen[$0]++'",
        ],
        cwd=Path.cwd(),
        check=True,
        text=True,
        capture_output=True,
    )

    assert result.stdout.splitlines() == ["nvme3n1"]


def test_fio_system_block_device_collection_has_valid_awk(tmp_path):
    lsblk = tmp_path / "lsblk"
    lsblk.write_text(
        textwrap.dedent(
            """\
            #!/bin/sh
            echo "nvme3n1 "
            echo "nvme3n1p1 nvme3n1"
            echo "nvme3n1p2 nvme3n1"
            """
        ),
        encoding="utf-8",
    )
    lsblk.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{tmp_path}{os.pathsep}{env['PATH']}"
    result = subprocess.run(
        [
            "bash",
            "-c",
            "source IO_Stress/lib/fio.sh; "
            "system_disk=nvme3n1; "
            "collect_system_block_devices 'nvme3n1 nvme3n1p1'",
        ],
        cwd=Path.cwd(),
        env=env,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout.split() == ["nvme3n1", "nvme3n1p1", "nvme3n1p2"]


def test_fio_output_has_successful_io_detects_any_positive_iops(tmp_path):
    ok_log = tmp_path / "ok.txt"
    ok_log.write_text(
        "read: IOPS=0, BW=0KiB/s\n"
        "write: IOPS=12.3k, BW=48.1MiB/s\n",
        encoding="utf-8",
    )
    fail_log = tmp_path / "fail.txt"
    fail_log.write_text(
        "read: IOPS=0, BW=0KiB/s\n"
        "write: IOPS=0, BW=0KiB/s\n"
        "fio: io_u error on file /dev/dp0-vd1: Invalid argument\n",
        encoding="utf-8",
    )
    missing = tmp_path / "missing.txt"

    result = subprocess.run(
        [
            "bash",
            "-lc",
            "source IO_Stress/lib/fio.sh; "
            f"fio_output_has_successful_io '{ok_log.as_posix()}' && echo ok_has_io=yes; "
            f"fio_output_has_successful_io '{fail_log.as_posix()}' || echo fail_has_io=no; "
            f"fio_output_has_successful_io '{missing.as_posix()}' || echo missing_has_io=no",
        ],
        cwd=Path.cwd(),
        check=True,
        text=True,
        capture_output=True,
    )

    assert "ok_has_io=yes" in result.stdout
    assert "fail_has_io=no" in result.stdout
    assert "missing_has_io=no" in result.stdout


def test_mix_fail_on_any_enabled_reads_env():
    result = subprocess.run(
        [
            "bash",
            "-lc",
            "source IO_Stress/lib/fio.sh; "
            "unset MIX_FAIL_ON_ANY; mix_fail_on_any_enabled || echo default=no; "
            "MIX_FAIL_ON_ANY=no mix_fail_on_any_enabled || echo no=no; "
            "MIX_FAIL_ON_ANY=yes mix_fail_on_any_enabled && echo yes=yes; "
            "MIX_FAIL_ON_ANY=YES mix_fail_on_any_enabled && echo YES=yes",
        ],
        cwd=Path.cwd(),
        check=True,
        text=True,
        capture_output=True,
    )

    assert "default=no" in result.stdout
    assert "no=no" in result.stdout
    assert "yes=yes" in result.stdout
    assert "YES=yes" in result.stdout


def test_fio_error_disks_parses_io_u_and_job_err(tmp_path):
    log = tmp_path / "mix.txt"
    log.write_text(
        "fio: io_u error on file /dev/dp8-vd2: Input/output error\n"
        "dp8-vd3: (g=0): err= 5:\n"
        "write: IOPS=0, BW=0KiB/s\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            "bash",
            "-lc",
            "source IO_Stress/lib/fio.sh; "
            f"fio_error_disks '{log.as_posix()}' | tr '\\n' ' '; echo",
        ],
        cwd=Path.cwd(),
        check=True,
        text=True,
        capture_output=True,
    )

    assert "dp8-vd2" in result.stdout
    assert "dp8-vd3" in result.stdout
