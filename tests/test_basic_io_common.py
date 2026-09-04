from decimal import Decimal
from pathlib import Path

import pytest

from test_items import basic_io_common
from test_items.basic_io_common import (
    EXCLUDED_NVME_MODELS,
    CommandLog,
    MIN_MULTI_RAID_DISKS,
    MULTI_RAID_VD_COUNT,
    NvmeDisk,
    create_raid5_vds,
    create_raid_vds,
    drives_expr,
    expected_degraded_vd_count,
    parse_dpraid_physical_devices,
    parse_dpraid_slots,
    parse_dpraid_virtual_ids,
    parse_lsblk_pairs,
    parse_nvme_list,
    partition_disks_for_multi_raid,
    prepare_basic_raid5_vds,
    resolve_logical_block_size,
    split_groups,
    usable_capacity_gb,
    vd_create_cmd,
    vd_size,
    vd_size_gb_for_raid,
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
    # Capacity must come from the total after '/', not the used size before it.
    assert disks[2].size_gb == Decimal("9010000.00")
    assert disks[2].model == "DAPUSTOR DPRP5108T0TF06T4000"
    assert disks[2].model in EXCLUDED_NVME_MODELS


def test_parse_nvme_list_uses_total_capacity_when_used_is_zero():
    text = """
Node             SN                   Model                                    Namespace Usage                      Format           FW Rev
---------------- -------------------- ---------------------------------------- --------- -------------------------- ---------------- --------
/dev/nvme5n1     SN5                  DAPUSTOR DPRD3108T8T506T4000             1           0.00   B /   6.40  TB    512   B +  0 B   1.0
/dev/nvme8n1     SN8                  DAPUSTOR DPRD3108T8T506T4000             1           3.84  TB /   3.84  TB    512   B +  0 B   1.0
"""

    disks = parse_nvme_list(text)

    assert [disk.namespace for disk in disks] == ["nvme5n1", "nvme8n1"]
    assert disks[0].size_gb == Decimal("6400.00")
    assert disks[1].size_gb == Decimal("3840.00")


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


def test_discover_nvme_data_disks_excludes_every_namespace_on_system_controller(monkeypatch):
    text = """
Node             SN                   Model                                    Namespace Usage                      Format           FW Rev
---------------- -------------------- ---------------------------------------- --------- -------------------------- ---------------- --------
/dev/nvme0n1     SYS                  Data NVMe                                1           1.00  TB /   1.00  TB    512   B +  0 B   1.0
/dev/nvme0n2     DATA                 Data NVMe                                2           1.00  TB /   1.00  TB    512   B +  0 B   1.0
/dev/nvme1n1     D1                   Data NVMe                                1           1.00  TB /   1.00  TB    512   B +  0 B   1.0
/dev/nvme2n1     D2                   Data NVMe                                1           1.00  TB /   1.00  TB    512   B +  0 B   1.0
"""

    class Result:
        stdout = text
        returncode = 0

    monkeypatch.setattr(basic_io_common, "protected_system_devices", lambda log: {"nvme0n1"})
    monkeypatch.setattr(basic_io_common, "mounted_devices", lambda log: set())
    monkeypatch.setattr(basic_io_common, "run_cmd", lambda cmd, log, check=True, shell=False: Result())

    disks = basic_io_common.discover_nvme_data_disks(CommandLog())

    assert [disk.namespace for disk in disks] == ["nvme1n1", "nvme2n1"]


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


def test_resolve_logical_block_size_accepts_512_and_4096(monkeypatch):
    monkeypatch.delenv("LOGICAL_BLOCK_SIZE", raising=False)
    assert resolve_logical_block_size() == 512
    assert resolve_logical_block_size("4096") == 4096
    monkeypatch.setenv("LOGICAL_BLOCK_SIZE", "4096")
    assert resolve_logical_block_size() == 4096


def test_resolve_logical_block_size_rejects_invalid_value():
    with pytest.raises(AssertionError, match="LOGICAL_BLOCK_SIZE must be one of"):
        resolve_logical_block_size("1024")


def test_vd_create_cmd_includes_logical_block_size():
    assert vd_create_cmd("0-5", 6512, 4096) == [
        "dpraid",
        "/c0",
        "add",
        "vd",
        "r=5",
        "Size=6512GB",
        "Strip=4",
        "LogicalBlockSize=4096",
        "drives=0-5",
    ]


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
        ["dpraid", "/c0", "add", "vd", "r=5", "Size=8226GB", "Strip=4", "LogicalBlockSize=512", "drives=0-6"]
    ] * 4
    assert add_vd_commands[4:] == [
        ["dpraid", "/c0", "add", "vd", "r=5", "Size=9597GB", "Strip=4", "LogicalBlockSize=512", "drives=7-14"]
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
    assert add_vd_commands[0] == ["dpraid", "/c0", "add", "vd", "r=5", "Size=8226GB", "Strip=4", "LogicalBlockSize=512", "drives=0-6"]
    assert add_vd_commands[4] == ["dpraid", "/c0", "add", "vd", "r=5", "Size=9597GB", "Strip=4", "LogicalBlockSize=512", "drives=7-14"]


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
    assert add_vd_commands[0] == ["dpraid", "/c0", "add", "vd", "r=5", "Size=6854GB", "Strip=4", "LogicalBlockSize=512", "drives=0-5"]
    assert add_vd_commands[1:] == [
        ["dpraid", "/c0", "add", "vd", "r=5", "Size=6512GB", "Strip=4", "LogicalBlockSize=512", "drives=0-5"]
    ] * 4


def test_create_raid5_vds_stops_when_retry_size_would_become_non_positive(monkeypatch):
    group = [
        NvmeDisk(namespace=f"nvme{i}n1", controller=f"nvme{i}", size_gb=Decimal("1"), did=i)
        for i in range(6)
    ]

    def fake_run_cmd(cmd, log, check=True, shell=False):
        class Result:
            stdout = ""
            returncode = 0

        result = Result()
        if cmd == ["dpraid", "/c0/vall", "show"]:
            result.stdout = ""
        elif cmd[:4] == ["dpraid", "/c0", "add", "vd"]:
            result.stdout = "DriveGroup: Cannot allocate memory\n"
            result.returncode = 255
        return result

    monkeypatch.setattr(basic_io_common, "run_cmd", fake_run_cmd)
    monkeypatch.setattr(basic_io_common, "VD_SIZE_RESERVE_PERCENT", Decimal("0"))
    monkeypatch.setattr(basic_io_common, "VD_SIZE_RETRY_STEP_PERCENT", Decimal("100"))

    try:
        create_raid5_vds([group], CommandLog())
        raise AssertionError("expected non-positive retry size to fail")
    except AssertionError as exc:
        assert "next Size would be" in str(exc)


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

    def fake_run_cmd(cmd, log, check=True, shell=False, env=None):
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
    assert calls[len(expected_cleanup)] == ["nvme", "list"]
    assert ["dpraid", "/c0", "add", "disk", "/dev/nvme0"] in calls
    assert len(disks) == 15
    assert [len(group) for group in groups] == [7, 8]
    assert vd_output == "vd output"
    assert ["dpraid", "/c0", "add", "vd", "r=5", "Size=8226GB", "Strip=4", "LogicalBlockSize=512", "drives=0-6"] in calls
    assert ["dpraid", "/c0", "add", "vd", "r=5", "Size=9597GB", "Strip=4", "LogicalBlockSize=512", "drives=7-14"] in calls


def test_clear_csd_flash_and_cache_only_runs_dirty_csd_helper(monkeypatch):
    calls = []
    disks = [
        NvmeDisk(namespace="nvme0n1", controller="nvme0", size_gb=Decimal("6400")),
        NvmeDisk(namespace="nvme1n1", controller="nvme1", size_gb=Decimal("6400")),
    ]

    def fake_run_cmd(cmd, log, check=True, shell=False, env=None):
        calls.append((cmd, shell, env))

        class Result:
            stdout = ""
            returncode = 0

        return Result()

    monkeypatch.setattr(basic_io_common, "run_cmd", fake_run_cmd)
    basic_io_common.clear_csd_flash_and_cache(disks, CommandLog())

    assert len(calls) == 1
    cmd, shell, env = calls[0]
    assert shell is False
    assert cmd[0] == "bash"
    assert "clear_8p_csd_flash.sh" in cmd[1]
    assert env is None or env.get("FORCE_CLEAR_ALL") != "1"
    assert "flash-clear.sh" not in " ".join(cmd if isinstance(cmd, list) else [cmd])


def test_release_and_clear_csd_rmmod_insmod_then_force_clears(monkeypatch):
    calls = []
    disks = [NvmeDisk(namespace="nvme2n1", controller="nvme2", size_gb=Decimal("1000"))]
    draid_loaded = {"value": True}

    def fake_run_cmd(cmd, log, check=True, shell=False, env=None):
        calls.append((cmd, env))

        class Result:
            stdout = ""
            returncode = 0

        result = Result()
        if isinstance(cmd, list) and cmd[:3] == ["modinfo", "-F", "name"]:
            result.stdout = "draid\n"
        elif isinstance(cmd, str) and "grep -q '^draid ' /proc/modules" in cmd:
            result.returncode = 0 if draid_loaded["value"] else 1
        elif cmd == ["rmmod", "draid"]:
            draid_loaded["value"] = False
        elif isinstance(cmd, list) and cmd and cmd[0] == "insmod":
            draid_loaded["value"] = True
        return result

    monkeypatch.setattr(basic_io_common, "run_cmd", fake_run_cmd)
    monkeypatch.setattr(basic_io_common, "draid_ko_path", lambda: Path("kernel_driver/drivers/draid/draid.ko"))
    monkeypatch.setattr(Path, "is_file", lambda self: True)

    basic_io_common.release_and_clear_csd(disks, CommandLog())

    rmmod_idxs = [i for i, (cmd, _) in enumerate(calls) if cmd == ["rmmod", "draid"]]
    insmod_idxs = [
        i for i, (cmd, _) in enumerate(calls) if isinstance(cmd, list) and cmd and cmd[0] == "insmod"
    ]
    clear_idx = next(
        i
        for i, (cmd, env) in enumerate(calls)
        if isinstance(cmd, list)
        and len(cmd) >= 2
        and "clear_8p_csd_flash.sh" in str(cmd[1])
    )
    assert len(rmmod_idxs) >= 2
    assert len(insmod_idxs) >= 2
    assert rmmod_idxs[0] < insmod_idxs[0] < clear_idx < rmmod_idxs[1] < insmod_idxs[1]
    assert calls[clear_idx][1]["FORCE_CLEAR_ALL"] == "1"
    assert draid_loaded["value"] is True


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


def test_power_cycle_uses_pci_remove_and_rescan_on_qemu_and_physical(monkeypatch):
    calls = []
    disk = NvmeDisk(namespace="nvme0n1", controller="nvme0", size_gb=Decimal("1"), bdf="0000:01:00.0", did=0)
    original_exists = basic_io_common.Path.exists

    def fake_run_cmd(cmd, log, check=True, shell=False):
        calls.append((cmd, shell))

        class Result:
            stdout = ""
            returncode = 0

        return Result()

    def fake_exists(self):
        normalized = str(self).replace("\\", "/")
        if normalized.endswith("/sys/bus/pci/devices/0000:01:00.0/remove"):
            return True
        return original_exists(self)

    monkeypatch.delenv("QEMU_VM_TARGET", raising=False)
    monkeypatch.setattr(basic_io_common, "run_cmd", fake_run_cmd)
    monkeypatch.setattr(basic_io_common.Path, "exists", fake_exists)

    basic_io_common.power_cycle_one_disk_per_group([[disk]], CommandLog())

    assert ("echo 1 > /sys/bus/pci/devices/0000:01:00.0/remove", True) in calls
    assert (["sleep", "1"], False) in calls
    assert ("echo 1 > /sys/bus/pci/rescan", True) in calls
    assert (["sleep", "2"], False) in calls
    assert not any("/sys/bus/pci/slots/" in str(cmd) for cmd, _ in calls)

    calls.clear()
    monkeypatch.setenv("QEMU_VM_TARGET", "1")
    basic_io_common.power_cycle_one_disk_per_group([[disk]], CommandLog())
    assert ("echo 1 > /sys/bus/pci/devices/0000:01:00.0/remove", True) in calls
    assert ("echo 1 > /sys/bus/pci/rescan", True) in calls


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


def test_partition_disks_for_multi_raid_uses_fixed_layout():
    disks = [
        NvmeDisk(namespace=f"nvme{i}n1", controller=f"nvme{i}", size_gb=Decimal("960.20"), did=i)
        for i in range(MIN_MULTI_RAID_DISKS)
    ]

    groups = partition_disks_for_multi_raid(disks)

    assert [(spec.raid_level, len(spec.disks)) for spec in groups] == [
        (0, 1),
        (0, 2),
        (1, 2),
        (10, 4),
        (50, 6),
    ]
    assert [disk.did for spec in groups for disk in spec.disks] == list(range(MIN_MULTI_RAID_DISKS))


def test_partition_disks_for_multi_raid_requires_minimum_disks():
    disks = [
        NvmeDisk(namespace=f"nvme{i}n1", controller=f"nvme{i}", size_gb=Decimal("960.20"), did=i)
        for i in range(MIN_MULTI_RAID_DISKS - 1)
    ]

    with pytest.raises(AssertionError, match=f"Need at least {MIN_MULTI_RAID_DISKS}"):
        partition_disks_for_multi_raid(disks)


def test_vd_size_gb_for_raid_levels():
    group = [
        NvmeDisk(namespace="nvme0n1", controller="nvme0", size_gb=Decimal("960.20"), did=0),
        NvmeDisk(namespace="nvme1n1", controller="nvme1", size_gb=Decimal("900.00"), did=1),
        NvmeDisk(namespace="nvme2n1", controller="nvme2", size_gb=Decimal("960.20"), did=2),
        NvmeDisk(namespace="nvme3n1", controller="nvme3", size_gb=Decimal("960.20"), did=3),
    ]

    assert usable_capacity_gb(0, 2, Decimal("900")) == Decimal("1800")
    assert usable_capacity_gb(1, 2, Decimal("900")) == Decimal("900")
    assert usable_capacity_gb(10, 4, Decimal("900")) == Decimal("1800")
    assert usable_capacity_gb(50, 6, Decimal("900")) == Decimal("3600")
    assert vd_size_gb_for_raid(0, group[:1]) == 240
    assert vd_size_gb_for_raid(1, group[:2]) == 225
    assert vd_size_gb_for_raid(10, group) == 450
    assert vd_size_gb_for_raid(50, group + group[:2]) == 900


def test_vd_create_cmd_supports_raid_level():
    assert vd_create_cmd("0-1", 100, 512, raid_level=10) == [
        "dpraid",
        "/c0",
        "add",
        "vd",
        "r=10",
        "Size=100GB",
        "Strip=4",
        "LogicalBlockSize=512",
        "drives=0-1",
    ]


def test_vd_create_cmd_adds_pd_per_array_for_raid50():
    assert vd_create_cmd("9-14", 5484, 512, raid_level=50) == [
        "dpraid",
        "/c0",
        "add",
        "vd",
        "r=50",
        "Size=5484GB",
        "Strip=4",
        "PDperArray=3",
        "LogicalBlockSize=512",
        "drives=9-14",
    ]


def test_create_raid_vds_creates_four_vds_per_group(monkeypatch):
    commands = []
    disks = [
        NvmeDisk(namespace=f"nvme{i}n1", controller=f"nvme{i}", size_gb=Decimal("5961.593"), did=i)
        for i in range(15)
    ]
    group_specs = [(spec.disks, spec.raid_level) for spec in partition_disks_for_multi_raid(disks)]

    def fake_run_cmd(cmd, log, check=True, shell=False):
        commands.append(cmd)

        class Result:
            stdout = ""
            returncode = 0

        return Result()

    monkeypatch.setattr(basic_io_common, "run_cmd", fake_run_cmd)
    create_raid_vds(group_specs, CommandLog())

    add_vd_commands = [cmd for cmd in commands if cmd[:4] == ["dpraid", "/c0", "add", "vd"]]
    assert len(add_vd_commands) == MULTI_RAID_VD_COUNT
    assert add_vd_commands[0] == [
        "dpraid",
        "/c0",
        "add",
        "vd",
        "r=0",
        "Size=1370GB",
        "Strip=4",
        "LogicalBlockSize=512",
        "drives=0",
    ]
    assert add_vd_commands[4] == [
        "dpraid",
        "/c0",
        "add",
        "vd",
        "r=0",
        "Size=2741GB",
        "Strip=4",
        "LogicalBlockSize=512",
        "drives=1-2",
    ]
    assert add_vd_commands[8] == [
        "dpraid",
        "/c0",
        "add",
        "vd",
        "r=1",
        "Size=1370GB",
        "Strip=4",
        "LogicalBlockSize=512",
        "drives=3-4",
    ]
    assert add_vd_commands[12] == [
        "dpraid",
        "/c0",
        "add",
        "vd",
        "r=10",
        "Size=2741GB",
        "Strip=4",
        "LogicalBlockSize=512",
        "drives=5-8",
    ]
    assert add_vd_commands[16] == [
        "dpraid",
        "/c0",
        "add",
        "vd",
        "r=50",
        "Size=5484GB",
        "Strip=4",
        "PDperArray=3",
        "LogicalBlockSize=512",
        "drives=9-14",
    ]


def test_expected_degraded_vd_count_skips_raid0_groups():
    group_specs = partition_disks_for_multi_raid(
        [
            NvmeDisk(namespace=f"nvme{i}n1", controller=f"nvme{i}", size_gb=Decimal("960.20"), did=i)
            for i in range(MIN_MULTI_RAID_DISKS)
        ]
    )

    assert expected_degraded_vd_count(group_specs) == 12


def test_degrade_non_raid0_groups_only_power_cycles_non_raid0(monkeypatch):
    calls = []
    group_specs = partition_disks_for_multi_raid(
        [
            NvmeDisk(
                namespace=f"nvme{i}n1",
                controller=f"nvme{i}",
                size_gb=Decimal("960.20"),
                did=i,
                bdf=f"0000:{i:02d}:00.0",
            )
            for i in range(MIN_MULTI_RAID_DISKS)
        ]
    )

    def fake_power_cycle(groups, log):
        calls.append([[disk.did for disk in group] for group in groups])

    monkeypatch.setattr(basic_io_common, "power_cycle_one_disk_per_group", fake_power_cycle)
    basic_io_common.degrade_non_raid0_groups(group_specs, CommandLog())

    assert calls == [[[3, 4], [5, 6, 7, 8], [9, 10, 11, 12, 13, 14]]]


def test_run_cmd_emits_heartbeat_while_command_blocks():
    log = CommandLog()
    result = basic_io_common.run_cmd(
        ["python", "-c", "import time; time.sleep(1.2)"],
        log,
        check=True,
        heartbeat_seconds=1,
    )

    assert result.returncode == 0
    text = "\n".join(log.lines)
    assert "[CMD_START]" in text
    assert "[CMD_WAIT] still running" in text
    assert "[CMD_END] rc=0 elapsed=" in text
