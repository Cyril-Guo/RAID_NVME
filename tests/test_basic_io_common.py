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


def test_discover_nvme_data_disks_excludes_qemu_nvme_ctrl(monkeypatch):
    text = """
Node             SN                   Model                                    Namespace Usage                      Format           FW Rev
---------------- -------------------- ---------------------------------------- --------- -------------------------- ---------------- --------
/dev/nvme0n1     nvme0                QEMU NVMe Ctrl                           1           3.22  GB /   3.22  GB    512   B +  0 B   1.0
/dev/nvme1n1     nvme7                QEMU NVMe Ctrl                           1           3.22  GB /   3.22  GB    512   B +  0 B   1.0
/dev/nvme2n1     SN2                  DAPUSTOR DPRD3108T0T506T4000             1           6.40  TB /   6.40  TB    512   B +  0 B   1.0
/dev/nvme3n1     SN3                  DAPUSTOR DPRD3108T0T506T4000             1           6.40  TB /   6.40  TB    512   B +  0 B   1.0
"""

    class Result:
        stdout = text
        returncode = 0

    monkeypatch.setattr(basic_io_common, "protected_system_devices", lambda log: set())
    monkeypatch.setattr(basic_io_common, "mounted_devices", lambda log: set())
    monkeypatch.setattr(basic_io_common, "run_cmd", lambda cmd, log, check=True, shell=False: Result())

    disks = basic_io_common.discover_nvme_data_disks(CommandLog())

    assert [disk.namespace for disk in disks] == ["nvme2n1", "nvme3n1"]
    assert "QEMU NVMe Ctrl" in EXCLUDED_NVME_MODELS


def test_discover_nvme_data_disks_sorts_by_inventory_bdf(monkeypatch):
    text = """
Node             SN                   Model                                    Namespace Usage                      Format           FW Rev
---------------- -------------------- ---------------------------------------- --------- -------------------------- ---------------- --------
/dev/nvme10n1    SN10                 DAPUSTOR DPRD3108T0T506T4000             1           6.40  TB /   6.40  TB    512   B +  0 B   1.0
/dev/nvme21n1    SN21                 DAPUSTOR DPRD3108T0T506T4000             1           6.40  TB /   6.40  TB    512   B +  0 B   1.0
/dev/nvme3n1     SN3                  DAPUSTOR DPRD3108T0T506T4000             1           6.40  TB /   6.40  TB    512   B +  0 B   1.0
"""
    inventory = [
        NvmeDisk(namespace="nvme10n1", controller="nvme10", size_gb=Decimal("6400"), sn="SN10", bdf="0000:10:00.0"),
        NvmeDisk(namespace="nvme21n1", controller="nvme21", size_gb=Decimal("6400"), sn="SN21", bdf="0000:21:00.0"),
        NvmeDisk(namespace="nvme3n1", controller="nvme3", size_gb=Decimal("6400"), sn="SN3", bdf="0000:03:00.0"),
    ]

    class Result:
        stdout = text
        returncode = 0

    monkeypatch.setattr(basic_io_common, "protected_system_devices", lambda log: set())
    monkeypatch.setattr(basic_io_common, "mounted_devices", lambda log: set())
    monkeypatch.setattr(basic_io_common, "run_cmd", lambda cmd, log, check=True, shell=False: Result())

    disks = basic_io_common.discover_nvme_data_disks(CommandLog(), inventory)

    assert [disk.controller for disk in disks] == ["nvme3", "nvme10", "nvme21"]


def test_discover_nvme_data_disks_uses_one_namespace_per_controller(monkeypatch):
    text = """
Node             SN                   Model                                    Namespace Usage                      Format           FW Rev
---------------- -------------------- ---------------------------------------- --------- -------------------------- ---------------- --------
/dev/nvme23n2    SN23N2               DAPUSTOR DPRD3108T0T506T4000             1           6.40  TB /   6.40  TB    512   B +  0 B   1.0
/dev/nvme23n1    SN23N1               DAPUSTOR DPRD3108T0T506T4000             1           6.40  TB /   6.40  TB    512   B +  0 B   1.0
/dev/nvme24n2    SN24N2               DAPUSTOR DPRD3108T0T506T4000             1           6.40  TB /   6.40  TB    512   B +  0 B   1.0
"""

    class Result:
        stdout = text
        returncode = 0

    monkeypatch.setattr(basic_io_common, "protected_system_devices", lambda log: set())
    monkeypatch.setattr(basic_io_common, "mounted_devices", lambda log: set())
    monkeypatch.setattr(basic_io_common, "run_cmd", lambda cmd, log, check=True, shell=False: Result())

    disks = basic_io_common.discover_nvme_data_disks(CommandLog())

    assert [disk.namespace for disk in disks] == ["nvme23n1", "nvme24n2"]
    assert [disk.controller for disk in disks] == ["nvme23", "nvme24"]


def test_nvme_inventory_excludes_qemu_nvme_ctrl(monkeypatch):
    text = """
Node             SN                   Model                                    Namespace Usage                      Format           FW Rev
---------------- -------------------- ---------------------------------------- --------- -------------------------- ---------------- --------
/dev/nvme0n1     nvme0                QEMU NVMe Ctrl                           1           3.22  GB /   3.22  GB    512   B +  0 B   1.0
/dev/nvme2n1     SN2                  DAPUSTOR DPRD3108T0T506T4000             1           6.40  TB /   6.40  TB    512   B +  0 B   1.0
"""

    class Result:
        stdout = text
        returncode = 0

    monkeypatch.setattr(basic_io_common, "run_cmd", lambda cmd, log, check=True, shell=False: Result())

    disks = basic_io_common.nvme_inventory(CommandLog())

    assert [disk.namespace for disk in disks] == ["nvme2n1"]


def test_nvme_inventory_uses_one_namespace_per_controller(monkeypatch):
    text = """
Node             SN                   Model                                    Namespace Usage                      Format           FW Rev
---------------- -------------------- ---------------------------------------- --------- -------------------------- ---------------- --------
/dev/nvme23n2    SN23N2               DAPUSTOR DPRD3108T0T506T4000             1           6.40  TB /   6.40  TB    512   B +  0 B   1.0
/dev/nvme23n1    SN23N1               DAPUSTOR DPRD3108T0T506T4000             1           6.40  TB /   6.40  TB    512   B +  0 B   1.0
/dev/nvme24n2    SN24N2               DAPUSTOR DPRD3108T0T506T4000             1           6.40  TB /   6.40  TB    512   B +  0 B   1.0
"""

    class Result:
        stdout = text
        returncode = 0

    monkeypatch.setattr(basic_io_common, "run_cmd", lambda cmd, log, check=True, shell=False: Result())

    disks = basic_io_common.nvme_inventory(CommandLog())

    assert [disk.namespace for disk in disks] == ["nvme23n1", "nvme24n2"]


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

    add_vd_commands = [cmd for cmd in commands if cmd[:4] == ["dpraid", "/c0", "add", "vd"]]
    assert len(add_vd_commands) == 8
    assert add_vd_commands[:4] == [
        ["dpraid", "/c0", "add", "vd", "r=5", "Size=8226GB", "Strip=4", "drives=0-6"]
    ] * 4
    assert add_vd_commands[4:] == [
        ["dpraid", "/c0", "add", "vd", "r=5", "Size=9597GB", "Strip=4", "drives=7-14"]
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
    add_vd_commands = [cmd for cmd in commands if cmd[:4] == ["dpraid", "/c0", "add", "vd"]]
    assert add_vd_commands[0] == ["dpraid", "/c0", "add", "vd", "r=5", "Size=8226GB", "Strip=4", "drives=0-6"]
    assert add_vd_commands[4] == ["dpraid", "/c0", "add", "vd", "r=5", "Size=9597GB", "Strip=4", "drives=7-14"]


def test_create_raid5_vds_retries_with_smaller_size_after_allocation_failure(monkeypatch):
    commands = []
    add_attempts = 0
    group = [
        NvmeDisk(namespace=f"nvme{i}n1", controller=f"nvme{i}", size_gb=Decimal("5961.593"), did=i)
        for i in range(6)
    ]

    def fake_run_cmd(cmd, log, check=True, shell=False):
        nonlocal add_attempts
        commands.append(cmd)

        class Result:
            stdout = ""
            returncode = 0

        result = Result()
        if cmd == ["dpraid", "/c0/vall", "show"]:
            result.stdout = ""
        elif cmd[:4] == ["dpraid", "/c0", "add", "vd"]:
            add_attempts += 1
            if add_attempts == 1:
                result.stdout = "DriveGroup: Cannot allocate memory\n"
                result.returncode = 255
        return result

    monkeypatch.setattr(basic_io_common, "run_cmd", fake_run_cmd)

    create_raid5_vds([group], CommandLog())

    add_vd_commands = [cmd for cmd in commands if cmd[:4] == ["dpraid", "/c0", "add", "vd"]]
    assert add_vd_commands[0] == ["dpraid", "/c0", "add", "vd", "r=5", "Size=6854GB", "Strip=4", "drives=0-5"]
    assert add_vd_commands[1:] == [
        ["dpraid", "/c0", "add", "vd", "r=5", "Size=6512GB", "Strip=4", "drives=0-5"]
    ] * 4


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

    monkeypatch.setenv("QEMU_VM_TARGET", "1")

    def fake_nvme_inventory(log):
        calls.append(["nvme", "list"])
        return nvme_disks

    monkeypatch.setattr(basic_io_common, "nvme_inventory", fake_nvme_inventory)
    monkeypatch.setattr(basic_io_common, "query_bdf", lambda disk, log: None)
    monkeypatch.setattr(basic_io_common, "show_physical_devices", lambda log: dpraid_show)
    monkeypatch.setattr(basic_io_common, "verify_vd_count", lambda log, expected=8: [f"dp0-vd{i}" for i in range(1, 9)])
    show_virtual_outputs = iter([existing_vd_show, "", "", "vd output"])
    monkeypatch.setattr(basic_io_common, "show_virtual_devices", lambda log: next(show_virtual_outputs))
    monkeypatch.setattr(basic_io_common, "discover_nvme_data_disks", lambda log, inventory_disks=None: nvme_disks)

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
    assert calls[len(expected_cleanup) : len(expected_cleanup) + 3] == [
        ["rmmod", "draid"],
        ["insmod", "kernel_driver/drivers/draid/draid.ko"],
        ["nvme", "list"],
    ]
    assert ["dpraid", "/c0", "add", "disk", "/dev/nvme0"] in calls
    assert len(disks) == 15
    assert [len(group) for group in groups] == [7, 8]
    assert vd_output == "vd output"
    assert ["dpraid", "/c0", "add", "vd", "r=5", "Size=8226GB", "Strip=4", "drives=0-6"] in calls
    assert ["dpraid", "/c0", "add", "vd", "r=5", "Size=9597GB", "Strip=4", "drives=7-14"] in calls


def test_physical_basic_io_does_not_reload_draid_after_pd_delete(monkeypatch):
    monkeypatch.delenv("QEMU_VM_TARGET", raising=False)
    calls = []
    monkeypatch.setattr(
        basic_io_common,
        "run_cmd",
        lambda cmd, log, check=True, shell=False: calls.append(cmd),
    )

    basic_io_common.reload_draid_after_qemu_pd_delete(CommandLog())

    assert calls == []


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


def test_qemu_vm_power_cycle_uses_pci_remove_and_rescan(monkeypatch):
    calls = []
    disk = NvmeDisk(namespace="nvme0n1", controller="nvme0", size_gb=Decimal("1"), bdf="0000:01:00.0", did=0)

    def fake_run_cmd(cmd, log, check=True, shell=False):
        calls.append((cmd, shell))

        class Result:
            stdout = ""
            returncode = 0

        return Result()

    monkeypatch.setenv("QEMU_VM_TARGET", "1")
    monkeypatch.setattr(basic_io_common, "run_cmd", fake_run_cmd)

    basic_io_common.power_cycle_one_disk_per_group([[disk]], CommandLog())

    assert ("echo 1 > /sys/bus/pci/devices/0000:01:00.0/remove", True) in calls
    assert (["sleep", "1"], False) in calls
    assert ("echo 1 > /sys/bus/pci/rescan", True) in calls
    assert (["sleep", "2"], False) in calls


def test_physical_power_cycle_still_uses_slot_power(monkeypatch):
    calls = []
    disk = NvmeDisk(namespace="nvme0n1", controller="nvme0", size_gb=Decimal("1"), bdf="0000:01:00.0", did=0)

    def fake_run_cmd(cmd, log, check=True, shell=False):
        calls.append((cmd, shell))

        class Result:
            stdout = ""
            returncode = 0

        return Result()

    monkeypatch.delenv("QEMU_VM_TARGET", raising=False)
    monkeypatch.setattr(basic_io_common, "slot_from_bdf", lambda bdf, log: "81")
    monkeypatch.setattr(basic_io_common, "run_cmd", fake_run_cmd)

    basic_io_common.power_cycle_one_disk_per_group([[disk]], CommandLog())

    assert ("echo 0 > /sys/bus/pci/slots/81/power", True) in calls
    assert ("echo 1 > /sys/bus/pci/slots/81/power", True) in calls
    assert not any("/sys/bus/pci/rescan" in str(cmd) for cmd, _ in calls)


def test_power_cycle_skips_excluded_nvme_models(monkeypatch):
    disk = NvmeDisk(
        namespace="nvme0n1",
        controller="nvme0",
        size_gb=Decimal("1"),
        model="QEMU NVMe Ctrl",
        bdf="0000:01:00.0",
        did=0,
    )
    monkeypatch.setenv("QEMU_VM_TARGET", "1")

    try:
        basic_io_common.power_cycle_one_disk_per_group([[disk]], CommandLog())
    except AssertionError as exc:
        assert "Cannot power-cycle group without BDF mapping" in str(exc)
    else:
        raise AssertionError("Expected excluded QEMU NVMe Ctrl disk to be skipped for power-cycle")
