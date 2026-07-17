from decimal import Decimal

from test_items import basic_io_common
from test_items.basic_io_common import (
    EXCLUDED_NVME_MODELS,
    CommandLog,
    NvmeDisk,
    create_raid5_vds,
    drives_expr,
    parse_dpraid_physical_devices,
    parse_dpraid_slots,
    parse_dpraid_virtual_ids,
    parse_lsblk_pairs,
    parse_nvme_list,
    prepare_basic_raid5_vds,
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
    assert [disk.sn for disk in disks] == ["SN0", "SN1", "SN-081FD192427DAB2C"]
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


def test_dpraid_show_dids_are_used_for_raid5_creation(monkeypatch):
    commands = []
    dpraid_show = "\n".join(
        [
            f"60:{i:<2} {i:<2} UnGo     null     5961.593 GB    NVMe  SSD  512 B DAPUSTOR DPRD3108T0T506T4000      SN{i:02d}"
            for i in range(15)
        ]
    )
    disks = parse_dpraid_physical_devices(dpraid_show)
    groups = split_groups(disks)

    def fake_run_cmd(cmd, log, check=True, shell=False):
        commands.append(cmd)

        class Result:
            stdout = ""
            returncode = 0

        return Result()

    monkeypatch.setattr(basic_io_common, "run_cmd", fake_run_cmd)
    create_raid5_vds(groups, CommandLog())

    assert [disk.did for disk in disks] == list(range(15))
    assert commands[0] == ["dpraid", "/c0", "add", "vd", "r=5", "Size=8942GB", "Strip=4", "drives=0-6"]
    assert commands[4] == ["dpraid", "/c0", "add", "vd", "r=5", "Size=10432GB", "Strip=4", "drives=7-14"]


def test_parse_dpraid_show_for_existing_vds_and_pds():
    vd_output = """
DG/VD  State  Consist TYPE
0/1    Opti   No      raid5
0/8    Opti   No      raid5
"""
    pd_output = "\n".join(
        [
            f"60:{i:<2} {i:<2} UnGo     null     5961.593 GB    NVMe  SSD  512 B DAPUSTOR DPRD3108T0T506T4000      SN{i:02d}"
            for i in range(15)
        ]
    )

    assert parse_dpraid_virtual_ids(vd_output) == [1, 8]
    assert parse_dpraid_slots(pd_output) == [f"s{i}" for i in range(15)]


def test_prepare_deletes_actual_existing_vds_and_pds_before_readding_disks(monkeypatch):
    calls = []
    existing_vd_show = """
DG/VD  State  Consist TYPE
0/1    Opti   No      raid5
0/3    Opti   No      raid5
0/8    Opti   No      raid5
"""
    dpraid_show = "\n".join(
        [
            f"60:{i:<2} {i:<2} UnGo     null     5961.593 GB    NVMe  SSD  512 B DAPUSTOR DPRD3108T0T506T4000      SN{i:02d}"
            for i in range(15)
        ]
    )
    nvme_disks = [
        NvmeDisk(namespace=f"nvme{i}n1", controller=f"nvme{i}", size_gb=Decimal("5961.593"), sn=f"SN{i:02d}")
        for i in range(15)
    ]

    monkeypatch.setattr(basic_io_common, "nvme_inventory", lambda log: nvme_disks)
    monkeypatch.setattr(basic_io_common, "query_bdf", lambda disk, log: None)
    monkeypatch.setattr(basic_io_common, "show_physical_devices", lambda log: dpraid_show)
    monkeypatch.setattr(basic_io_common, "verify_vd_count", lambda log, expected=8: [f"dp0-vd{i}" for i in range(1, 9)])
    show_virtual_outputs = iter([existing_vd_show, "vd output"])
    monkeypatch.setattr(basic_io_common, "show_virtual_devices", lambda log: next(show_virtual_outputs))
    monkeypatch.setattr(basic_io_common, "discover_nvme_data_disks", lambda log: nvme_disks)

    def fake_run_cmd(cmd, log, check=True, shell=False):
        calls.append(cmd)

        class Result:
            stdout = ""
            returncode = 0

        return Result()

    monkeypatch.setattr(basic_io_common, "run_cmd", fake_run_cmd)

    disks, groups, vd_output = prepare_basic_raid5_vds(CommandLog())

    expected_cleanup = [
        ["dpraid", "/c0/v1", "delete"],
        ["dpraid", "/c0/v3", "delete"],
        ["dpraid", "/c0/v8", "delete"],
    ] + [["dpraid", f"/c0/eall/s{i}", "delete"] for i in range(15)]
    assert calls[: len(expected_cleanup)] == expected_cleanup
    assert ["dpraid", "/c0", "add", "disk", "/dev/nvme0"] in calls
    assert len(disks) == 15
    assert [len(group) for group in groups] == [7, 8]
    assert vd_output == "vd output"
    assert ["dpraid", "/c0", "add", "vd", "r=5", "Size=8942GB", "Strip=4", "drives=0-6"] in calls
    assert ["dpraid", "/c0", "add", "vd", "r=5", "Size=10432GB", "Strip=4", "drives=7-14"] in calls


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
