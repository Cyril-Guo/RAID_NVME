from decimal import Decimal

from test_items.basic_io_common import NvmeDisk, drives_expr, parse_lsblk_pairs, parse_nvme_list, split_groups, vd_size


def test_parse_nvme_list_keeps_normal_capacity_devices():
    text = """
Node             SN                   Model                                    Namespace Usage                      Format           FW Rev
---------------- -------------------- ---------------------------------------- --------- -------------------------- ---------------- --------
/dev/nvme0n1     SN0                  DapuStor                                 1         960.20  GB / 960.20  GB    512   B +  0 B   1.0
/dev/nvme1n1     SN1                  DapuStor                                 1           1.92  TB /   1.92  TB    512   B +  0 B   1.0
"""

    disks = parse_nvme_list(text)

    assert [disk.namespace for disk in disks] == ["nvme0n1", "nvme1n1"]
    assert [disk.controller for disk in disks] == ["nvme0", "nvme1"]
    assert disks[0].size_gb == Decimal("960.20")
    assert disks[1].size_gb == Decimal("1920.00")


def test_split_groups_puts_odd_extra_disk_in_first_group():
    disks = [NvmeDisk(namespace=f"nvme{i}n1", controller=f"nvme{i}", size_gb=Decimal("960.20")) for i in range(15)]

    groups = split_groups(disks)

    assert len(groups[0]) == 8
    assert len(groups[1]) == 7


def test_raid5_vd_size_uses_min_capacity_times_count_divided_by_four():
    group = [
        NvmeDisk(namespace="nvme0n1", controller="nvme0", size_gb=Decimal("960.20"), did=0),
        NvmeDisk(namespace="nvme1n1", controller="nvme1", size_gb=Decimal("900.00"), did=1),
        NvmeDisk(namespace="nvme2n1", controller="nvme2", size_gb=Decimal("960.20"), did=2),
        NvmeDisk(namespace="nvme3n1", controller="nvme3", size_gb=Decimal("960.20"), did=3),
    ]

    assert vd_size(group) == "900GB"
    assert drives_expr(group) == "0-3"


def test_parse_lsblk_pairs_preserves_empty_parent_columns():
    text = 'NAME="sdc" PKNAME="" MOUNTPOINT="/mnt/data"\nNAME="sdc1" PKNAME="sdc" MOUNTPOINT=""\n'

    assert parse_lsblk_pairs(text) == [
        ("sdc", "", "/mnt/data"),
        ("sdc1", "sdc", ""),
    ]
