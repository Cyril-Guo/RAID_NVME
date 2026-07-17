from pathlib import Path
import os
import subprocess
import textwrap


def test_fio_runner_only_iterates_generated_log_configs():
    source = Path("IO_Stress/lib/fio.sh").read_text(encoding="utf-8")

    assert "grep '\\.log$'" in source
    assert "for configuration in `ls -p $Config_Dir | grep -v / | sort" not in source


def test_fio_system_disk_detection_handles_lvm_parent_disk():
    source = Path("IO_Stress/lib/fio.sh").read_text(encoding="utf-8")

    assert "normalize_system_disk" in source
    assert "lsblk -nr -o NAME,PKNAME,MOUNTPOINT" in source
    assert "findmnt -nvo SOURCE" in source
    assert "extract_parent_disk" in source
    assert "BASH_REMATCH[1]" in source


def test_fio_auto_disk_selection_prefers_draid_virtual_disks():
    source = Path("IO_Stress/lib/fio.sh").read_text(encoding="utf-8")

    assert "select_auto_test_disks" in source
    assert "grep -E '^dp[0-9]+-vd[0-9]+$'" in source
    assert "specified_disk_contains_system" in source
    assert "validate_test_disks" in source
    assert "assert_not_system_disk" in source
    assert "collect_system_block_devices" in source
    assert "device_has_mountpoint" in source


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
