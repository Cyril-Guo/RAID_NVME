from decimal import Decimal

from test_items import basic_io_common
from test_items.basic_io_common import (
    EXCLUDED_NVME_MODELS,
    CommandLog,
    NvmeDisk,
    create_raid5_vds,
    drives_expr,
    parse_lsblk_pairs,
    parse_nvme_list,
    split_groups,
    vd_size,
)


def test_parse_nvme_list_keeps_normal_capacity_devices():
    text = """
Node             SN                   Model                                    Namespace Usage                      Format           FW Rev
---------------- -------------------- ---------------------------------------- --------- -------------------------- ---------------- --------
/dev/nvme0n1     SN0                  DapuStor                                 1         960.20  GB / 960.20  GB    512   B +  0 B   1.0
/dev/nvme1n1     SN1                  DapuStor                                 1           1.92  TB /   1.92  TB    512   B +  0 B   1.0
/dev/nvme4n1     SN-081FD192427DAB2C  DAPUSTOR DPRP5108T0TF06T4000             1           0.00   B /   9.01  PB      4 KiB + 16 B   FC003104
"""

    disks = parse_nvme_list(text)

    assert [disk.namespace for disk in disks] == ["nvme0n1", "nvme1n1", "nvme4n1"]
    assert [disk.controller for disk in disks] == ["nvme0", "nvme1", "nvme4"]
    assert disks[0].size_gb == Decimal("960.20")
    assert disks[1].size_gb == Decimal("1920.00")
    assert disks[2].model == "DAPUSTOR DPRP5108T0TF06T4000"
    assert disks[2].model in EXCLUDED_NVME_MODELS


def test_split_groups_puts_odd_extra_disk_in_second_group():
    disks = [NvmeDisk(namespace=f"nvme{i}n1", controller=f"nvme{i}", size_gb=Decimal("960.20")) for i in range(15)]

    groups = split_groups(disks)

    assert len(groups[0]) == 7
    assert len(groups[1]) == 8


def test_raid5_vd_size_uses_raid5_usable_capacity_divided_by_four():
    group = [
        NvmeDisk(namespace="nvme0n1", controller="nvme0", size_gb=Decimal("960.20"), did=0),
        NvmeDisk(namespace="nvme1n1", controller="nvme1", size_gb=Decimal("900.00"), did=1),
        NvmeDisk(namespace="nvme2n1", controller="nvme2", size_gb=Decimal("960.20"), did=2),
        NvmeDisk(namespace="nvme3n1", controller="nvme3", size_gb=Decimal("960.20"), did=3),
    ]

    assert vd_size(group) == "675GB"
    assert drives_expr(group) == "0-3"


def test_create_raid5_vds_splits_15_disks_into_7_and_8_disk_groups(monkeypatch):
    commands = []
    disks = [
        NvmeDisk(namespace=f"nvme{i}n1", controller=f"nvme{i}", size_gb=Decimal("5961.593"), did=i)
        for i in range(15)
    ]
    groups = split_groups(disks)

    def fake_run_cmd(cmd, log, check=True, shell=False):
        commands.append(cmd)

        class Result:
            stdout = ""
            returncode = 0

        return Result()

    monkeypatch.setattr(basic_io_common, "run_cmd", fake_run_cmd)
    create_raid5_vds(groups, CommandLog())

    assert len(commands) == 8
    assert commands[:4] == [
        ["dpraid", "/c0", "add", "vd", "r=5", "Size=8942GB", "Strip=4", "drives=0-6"]
    ] * 4
    assert commands[4:] == [
        ["dpraid", "/c0", "add", "vd", "r=5", "Size=10432GB", "Strip=4", "drives=7-14"]
    ] * 4


def test_parse_lsblk_pairs_preserves_empty_parent_columns():
    text = 'NAME="sdc" PKNAME="" MOUNTPOINT="/mnt/data"\nNAME="sdc1" PKNAME="sdc" MOUNTPOINT=""\n'

    assert parse_lsblk_pairs(text) == [
        ("sdc", "", "/mnt/data"),
        ("sdc1", "sdc", ""),
    ]


def test_lsblk_rows_uses_pairs_without_raw_flag(monkeypatch):
    captured = {}

    def fake_run_cmd(cmd, log, check=True, shell=False):
        captured["cmd"] = cmd

        class Result:
            stdout = 'NAME="nvme3n1" PKNAME="" MOUNTPOINT=""\n'

        return Result()

    monkeypatch.setattr(basic_io_common, "run_cmd", fake_run_cmd)

    assert basic_io_common.lsblk_rows(log=None) == [("nvme3n1", "", "")]
    assert captured["cmd"] == ["lsblk", "-nP", "-o", "NAME,PKNAME,MOUNTPOINT"]
