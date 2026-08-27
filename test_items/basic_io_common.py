import os
import random
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path

import allure


@dataclass
class NvmeDisk:
    namespace: str
    controller: str
    size_gb: Decimal
    model: str = ""
    sn: str = ""
    bdf: str = ""
    did: int | None = None


@dataclass
class RaidGroupSpec:
    raid_level: int
    disks: list

    @property
    def label(self):
        return f"raid{self.raid_level}-{len(self.disks)}"


EXCLUDED_NVME_MODELS = {
    "DAPUSTOR DPRP5108T0TF06T4000",
    "QEMU NVMe Ctrl",
}
VDS_PER_GROUP = 4
VD_SIZE_RESERVE_PERCENT = Decimal("8")
VD_SIZE_RETRY_STEP_PERCENT = Decimal("5")
VD_SIZE_RETRY_LIMIT = 6
ALLOWED_LOGICAL_BLOCK_SIZES = {512, 4096}
DEFAULT_LOGICAL_BLOCK_SIZE = 512
MULTI_RAID_LEVELS = [0, 0, 1, 10, 50]
MULTI_RAID_DISK_COUNTS = [1, 2, 2, 4, 6]
MIN_MULTI_RAID_DISKS = sum(MULTI_RAID_DISK_COUNTS)
MULTI_RAID_VD_COUNT = len(MULTI_RAID_LEVELS) * VDS_PER_GROUP


def resolve_logical_block_size(value=None):
    if value is None:
        value = os.environ.get("LOGICAL_BLOCK_SIZE", str(DEFAULT_LOGICAL_BLOCK_SIZE))
    normalized = str(value).strip()
    if normalized not in {str(size) for size in ALLOWED_LOGICAL_BLOCK_SIZES}:
        raise AssertionError(
            f"LOGICAL_BLOCK_SIZE must be one of {sorted(ALLOWED_LOGICAL_BLOCK_SIZES)}, got: {value}"
        )
    return int(normalized)


def vd_create_cmd(expr, size_gb, logical_block_size, raid_level=5):
    cmd = [
        "dpraid",
        "/c0",
        "add",
        "vd",
        f"r={raid_level}",
        f"Size={size_gb}GB",
        "Strip=4",
    ]
    if raid_level == 50:
        cmd.append("PDperArray=3")
    cmd.extend(
        [
            f"LogicalBlockSize={logical_block_size}",
            f"drives={expr}",
        ]
    )
    return cmd


def is_excluded_nvme_model(model):
    return " ".join((model or "").split()) in EXCLUDED_NVME_MODELS


def nvme_controller_number(controller):
    match = re.fullmatch(r"nvme(\d+)", controller or "")
    if not match:
        return 10**9
    return int(match.group(1))


def nvme_namespace_number(namespace):
    match = re.fullmatch(r"nvme\d+n(\d+)", namespace or "")
    if not match:
        return 10**9
    return int(match.group(1))


def bdf_sort_key(bdf):
    match = re.fullmatch(
        r"([0-9a-fA-F]{4}):([0-9a-fA-F]{2}):([0-9a-fA-F]{2})\.([0-9a-fA-F])",
        bdf or "",
    )
    if not match:
        return (1, 0, 0, 0, 0)
    return (0, *(int(part, 16) for part in match.groups()))


def nvme_disk_sort_key(disk):
    return (
        *bdf_sort_key(disk.bdf),
        nvme_controller_number(disk.controller),
        nvme_namespace_number(disk.namespace),
        disk.namespace,
    )


def unique_nvme_controllers(disks, log=None):
    selected = {}
    for disk in sorted(disks, key=lambda item: (nvme_controller_number(item.controller), nvme_namespace_number(item.namespace))):
        if disk.controller not in selected:
            selected[disk.controller] = disk
            continue
        if log:
            log.write(f"Skip duplicate NVMe namespace for controller: {disk.namespace} -> {disk.controller}")
    return list(selected.values())


def apply_bdf_from_inventory(disks, inventory_disks):
    by_namespace = {disk.namespace: disk for disk in inventory_disks if disk.namespace}
    by_controller = {disk.controller: disk for disk in inventory_disks if disk.controller}
    by_sn = {disk.sn: disk for disk in inventory_disks if disk.sn}
    for disk in disks:
        inventory_disk = by_namespace.get(disk.namespace) or by_controller.get(disk.controller) or by_sn.get(disk.sn)
        if inventory_disk:
            disk.bdf = inventory_disk.bdf


def ts():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class CommandLog:
    def __init__(self):
        self.lines = []

    def write(self, line):
        text = f"[{ts()}] {line}"
        print(text)
        self.lines.append(text)

    def attach(self, name):
        allure.attach("\n".join(self.lines), name=name, attachment_type=allure.attachment_type.TEXT)


def run_cmd(cmd, log, check=True, shell=False, env=None):
    display = cmd if isinstance(cmd, str) else " ".join(cmd)
    log.write(f"$ {display}")
    result = subprocess.run(
        cmd,
        shell=shell,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
    )
    if result.stdout:
        for line in result.stdout.rstrip("\n").splitlines():
            log.write(line)
    log.write(f"[exit] {result.returncode}")
    if check and result.returncode != 0:
        raise AssertionError(f"Command failed rc={result.returncode}: {display}")
    return result


def normalize_block_name(device):
    name = str(device).strip()
    name = re.sub(r"^/dev/", "", name)
    name = re.sub(r"^mapper/", "", name)
    return name


def parse_lsblk_pairs(text):
    rows = []
    for line in text.splitlines():
        values = dict(re.findall(r'(\w+)="([^"]*)"', line))
        if values.get("NAME"):
            rows.append(
                (
                    values.get("NAME", ""),
                    values.get("PKNAME", ""),
                    values.get("MOUNTPOINT", ""),
                )
            )
    return rows


def lsblk_rows(log):
    result = run_cmd(["lsblk", "-nP", "-o", "NAME,PKNAME,MOUNTPOINT"], log, check=True)
    return parse_lsblk_pairs(result.stdout)


def protected_system_devices(log):
    protected = set()
    sources = []
    for mount_point in ("/", "/boot", "/boot/efi"):
        result = run_cmd(["findmnt", "-nvo", "SOURCE", mount_point], log, check=False)
        source = (result.stdout or "").strip().splitlines()
        if source:
            sources.append(normalize_block_name(source[0].split("[", 1)[0]))

    parent = {}
    rows = lsblk_rows(log)
    for name, pkname, mount_point in rows:
        parent[name] = pkname
        if mount_point in ("/", "/boot", "/boot/efi"):
            sources.extend([name, pkname])

    for source in sources:
        current = normalize_block_name(source)
        while current:
            protected.add(current)
            current = parent.get(current, "")

    changed = True
    while changed:
        changed = False
        for name, pkname, _ in rows:
            if pkname in protected and name not in protected:
                protected.add(name)
                changed = True

    log.write(f"Protected system block devices: {sorted(protected)}")
    return protected


def mounted_devices(log):
    mounted = set()
    for name, pkname, mount_point in lsblk_rows(log):
        if mount_point:
            mounted.add(name)
            if pkname:
                mounted.add(pkname)
    log.write(f"Mounted block devices: {sorted(mounted)}")
    return mounted


def _size_to_gb(size, unit):
    size = Decimal(size)
    unit = unit.upper()
    if unit == "PB":
        return size * Decimal("1000000")
    if unit == "TB":
        return size * Decimal("1000")
    if unit == "GB":
        return size
    if unit == "MB":
        return size / Decimal("1000")
    if unit == "KB":
        return size / Decimal("1000000")
    if unit == "B":
        return size / Decimal("1000000000")
    return size


def parse_nvme_list(text):
    disks = []
    for line in text.splitlines():
        # nvme list Usage column is "used / total"; always take total capacity after '/'.
        match = re.search(
            r"(/dev/(nvme\d+)n\d+)\s+(\S+)\s+(.+?)\s+\d+\s+"
            r"\d+(?:\.\d+)?\s+[KMGTP]?B\s*/\s*(\d+(?:\.\d+)?)\s+([KMGTP]?B)\b",
            line,
        )
        if not match:
            continue
        sn = match.group(3)
        model = " ".join(match.group(4).split())
        size_gb = _size_to_gb(match.group(5), match.group(6))
        disks.append(
            NvmeDisk(
                namespace=Path(match.group(1)).name,
                controller=match.group(2),
                size_gb=size_gb,
                model=model,
                sn=sn,
            )
        )
    return disks


def discover_nvme_data_disks(log, inventory_disks=None):
    protected = protected_system_devices(log)
    mounted = mounted_devices(log)
    result = run_cmd(["nvme", "list"], log, check=True)
    disks = []
    for disk in parse_nvme_list(result.stdout):
        if is_excluded_nvme_model(disk.model):
            log.write(f"Skip excluded NVMe model: {disk.namespace} {disk.model}")
            continue
        if disk.namespace in protected or disk.controller in protected:
            log.write(f"Skip system NVMe: {disk.namespace}")
            continue
        if disk.namespace in mounted or disk.controller in mounted:
            log.write(f"Skip mounted NVMe: {disk.namespace}")
            continue
        if disk.size_gb <= 0:
            log.write(f"Skip NVMe with invalid size: {disk.namespace} {disk.size_gb}GB")
            continue
        disks.append(disk)

    disks = unique_nvme_controllers(disks, log)
    if len(disks) < 2:
        raise AssertionError(f"Need at least 2 non-system NVMe disks, got {len(disks)}")
    if inventory_disks:
        apply_bdf_from_inventory(disks, inventory_disks)
    disks = sorted(disks, key=nvme_disk_sort_key)
    log.write(
        "Selected NVMe disks: "
        + ", ".join(f"{d.namespace}({d.model},{d.size_gb}GB,bdf={d.bdf or 'unknown'})" for d in disks)
    )
    return disks


def nvme_inventory(log):
    result = run_cmd(["nvme", "list"], log, check=True)
    disks = []
    for disk in parse_nvme_list(result.stdout):
        if is_excluded_nvme_model(disk.model):
            log.write(f"Skip excluded NVMe inventory model: {disk.namespace} {disk.model}")
            continue
        disks.append(disk)
    disks = unique_nvme_controllers(disks, log)
    log.write("NVMe inventory: " + ", ".join(f"{d.namespace}({d.sn},{d.size_gb}GB)" for d in disks))
    return disks


def query_bdf(disk, log):
    sysfs = f"/sys/block/{disk.namespace}/device/"
    result = run_cmd(f"ls {sysfs} -al", log, check=True, shell=True)
    match = re.search(r"([0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-9a-fA-F])", result.stdout)
    if not match:
        result = run_cmd(["readlink", "-f", sysfs], log, check=True)
        match = re.search(r"([0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-9a-fA-F])", result.stdout)
    if not match:
        raise AssertionError(f"Cannot resolve BDF for {disk.namespace}")
    disk.bdf = match.group(1)
    log.write(f"{disk.namespace} BDF: {disk.bdf}")


def split_groups(disks):
    split_at = len(disks) // 2
    return [disks[:split_at], disks[split_at:]]


def partition_disks_for_multi_raid(disks):
    if len(disks) < MIN_MULTI_RAID_DISKS:
        raise AssertionError(
            f"Need at least {MIN_MULTI_RAID_DISKS} disks for multi-RAID layout, got {len(disks)}"
        )
    groups = []
    index = 0
    for raid_level, disk_count in zip(MULTI_RAID_LEVELS, MULTI_RAID_DISK_COUNTS):
        groups.append(RaidGroupSpec(raid_level=raid_level, disks=disks[index : index + disk_count]))
        index += disk_count
    return groups


def show_virtual_devices(log):
    return run_cmd(["dpraid", "/c0/vall", "show"], log, check=True).stdout


def show_physical_devices(log):
    return run_cmd(["dpraid", "/c0/eall/sall", "show"], log, check=True).stdout


def parse_dpraid_virtual_ids(text):
    ids = []
    for line in text.splitlines():
        match = re.search(r"\b(\d+)/(\d+)\s+\S+\s+\S+\s+raid\d+\b", line, re.IGNORECASE)
        if match:
            ids.append(int(match.group(2)))
    return sorted(set(ids))


def delete_existing_vds(log):
    for index in parse_dpraid_virtual_ids(show_virtual_devices(log)):
        run_cmd(["dpraid", f"/c0/v{index}", "delete"], log, check=False)


def delete_existing_pds(log):
    for slot in parse_dpraid_slots(show_physical_devices(log)):
        run_cmd(["dpraid", f"/c0/eall/{slot}", "delete"], log, check=False)


def flash_clear_script_path():
    return Path(__file__).resolve().parents[1] / "ci" / "flash-clear.sh"


def clear_8p_script_path():
    return Path(__file__).resolve().parents[1] / "ci" / "clear_8p_csd_flash.sh"


def draid_ko_path():
    return Path(__file__).resolve().parents[1] / "kernel_driver" / "drivers" / "draid" / "draid.ko"


def nvme_controller_paths(disks):
    controllers = []
    seen = set()
    for disk in disks:
        controller = (disk.controller or "").strip()
        if not controller:
            continue
        path = f"/dev/{controller}"
        if path in seen:
            continue
        seen.add(path)
        controllers.append(path)
    return controllers


def draid_module_candidates(log):
    names = []
    ko = draid_ko_path()
    if ko.is_file():
        result = run_cmd(["modinfo", "-F", "name", str(ko)], log, check=False)
        for line in (result.stdout or "").splitlines():
            name = line.strip()
            if name:
                names.append(name)
                break
    names.append("draid")
    return list(dict.fromkeys(names))


def unload_draid_module(log):
    """Unload draid so NVMe controllers are released before CSD flash/cache clear."""
    log.write("Unload draid module before CSD flash/cache clear")
    for candidate in draid_module_candidates(log):
        loaded = run_cmd(f"grep -q '^{candidate} ' /proc/modules", log, check=False, shell=True)
        if loaded.returncode != 0:
            continue
        result = run_cmd(["rmmod", candidate], log, check=False)
        if result.returncode != 0:
            run_cmd(["modprobe", "-r", candidate], log, check=False)
    for candidate in draid_module_candidates(log):
        still = run_cmd(f"grep -q '^{candidate} ' /proc/modules", log, check=False, shell=True)
        if still.returncode == 0:
            raise AssertionError(f"draid module still loaded after unload attempt: {candidate}")
    log.write("draid module unloaded (or was not loaded)")


def load_draid_module(log):
    """Reload draid after CSD flash/cache clear so subsequent add disk/VD can proceed."""
    ko = draid_ko_path()
    if not ko.is_file():
        raise AssertionError(f"draid.ko not found: {ko}")
    log.write(f"Load draid module from {ko}")
    run_cmd(["sync"], log, check=False)
    run_cmd("echo 3 > /proc/sys/vm/drop_caches", log, check=False, shell=True)
    result = run_cmd(["insmod", str(ko)], log, check=False)
    if result.returncode != 0:
        run_cmd(["sync"], log, check=False)
        run_cmd("echo 3 > /proc/sys/vm/drop_caches", log, check=False, shell=True)
        run_cmd(["sleep", "2"], log, check=False)
        run_cmd(["insmod", str(ko)], log, check=True)
    module_name = draid_module_candidates(log)[0]
    loaded = run_cmd(f"grep -q '^{module_name} ' /proc/modules", log, check=False, shell=True)
    if loaded.returncode != 0:
        loaded = run_cmd("grep -q '^draid ' /proc/modules", log, check=False, shell=True)
    if loaded.returncode != 0:
        raise AssertionError(f"draid module not loaded after insmod: {ko}")
    log.write("draid module loaded")


def clear_csd_flash_and_cache(disks, log, force=False):
    """Clear CSD flash+cache via /dev/draid_dbg_accel* before rebuilding VDs.

    Uses clear_8p_csd_flash.sh. By default only clears when lspci shows DAPU
    Device 50d1 without "Kernel driver in use: draid-nvme". With force=True,
    always clears ALL /dev/draid_dbg_accel* (used for per-case refresh after
    rmmod/insmod, when devices are already rebound).
    Caller must ensure draid is loaded with ACCEL_CDEV=y first.
    """
    del disks  # discovery is done inside clear_8p_csd_flash.sh
    script = clear_8p_script_path()
    if not script.is_file():
        raise AssertionError(f"clear_8p script not found: {script}")
    env = os.environ.copy()
    if force:
        env["FORCE_CLEAR_ALL"] = "1"
        log.write("Force clear ALL draid accel devices (CSD flash+cache refresh)")
    else:
        log.write(
            "Clear dirty CSD flash+cache on ALL draid accel devices "
            "(lspci DAPU Device 50d1 without draid-nvme driver)"
        )
    run_cmd(["bash", str(script)], log, check=True, env=env)
    log.write("CSD flash+cache clear finished (or skipped: none dirty)")


def release_and_clear_csd(disks, log):
    """Force-clear all accel devices with a surrounding draid reload.

    Sequence:
      1) rmmod draid
      2) insmod draid.ko          (recreate /dev/draid_dbg_accel*)
      3) FORCE_CLEAR_ALL clear
      4) rmmod draid
      5) insmod draid.ko          (reload afterwards)
    Module stays loaded afterwards.

    CI env_prepare uses prepare_env.sh (dirty-check clear) instead of this helper.
    """
    log.write(
        "CSD refresh: rmmod -> insmod -> clear all /dev/draid_dbg_accel* "
        "-> rmmod -> insmod"
    )
    unload_draid_module(log)
    load_draid_module(log)
    clear_csd_flash_and_cache(disks, log, force=True)
    unload_draid_module(log)
    load_draid_module(log)


def run_env_prepare(log):
    """DUT environment prepare used by the env_prepare test case.

    Runs ci/prepare_env.sh: reclaim host, install dpraid, rebuild/reload draid,
    clear dirty CSD flash via accel devices, then clear leftover VD/PD.
    """
    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "ci" / "prepare_env.sh"
    if not script.is_file():
        raise AssertionError(f"Missing prepare script: {script}")

    env = os.environ.copy()
    env.setdefault("REMOTE_DIR", str(repo_root))
    env.setdefault("NODE_IP", env.get("NODE_IP", "local"))
    log.write("phase: env_prepare (dpraid / draid reload / CSD clear / VD-PD clear)")
    run_cmd(["bash", str(script)], log, check=True, shell=False, env=env)


def add_physical_disks(disks, log):
    for disk in disks:
        run_cmd(["dpraid", "/c0", "add", "disk", f"/dev/{disk.controller}"], log, check=True)


def parse_dpraid_physical_devices(text):
    disks = []
    for line in text.splitlines():
        match = re.search(
            r"\b\d+:\d+\s+(\d+)\s+UnGo\s+\S+\s+(\d+(?:\.\d+)?)\s+GB\s+\S+\s+\S+\s+\S+\s+\S+\s+(.+?)\s+(\S+)\s*$",
            line,
        )
        if not match:
            continue
        did = int(match.group(1))
        model = " ".join(match.group(3).split())
        sn = match.group(4)
        disks.append(
            NvmeDisk(
                namespace=f"did{did}",
                controller="",
                size_gb=Decimal(match.group(2)),
                model=model,
                sn=sn,
                did=did,
            )
        )
    return sorted(disks, key=lambda disk: disk.did if disk.did is not None else -1)


def parse_dpraid_slots(text):
    slots = []
    for line in text.splitlines():
        match = re.search(r"\b\d+:(\d+)\s+\d+\s+\S+\s+", line)
        if match:
            slots.append(f"s{int(match.group(1))}")
    return sorted(set(slots), key=lambda slot: int(slot[1:]))


def apply_bdf_from_nvme_inventory(dpraid_disks, nvme_disks, log):
    by_sn = {disk.sn: disk for disk in nvme_disks if disk.sn}
    for disk in dpraid_disks:
        nvme_disk = by_sn.get(disk.sn)
        if nvme_disk:
            disk.namespace = nvme_disk.namespace
            disk.controller = nvme_disk.controller
            disk.bdf = nvme_disk.bdf
    missing = [f"DID{disk.did}:{disk.sn}" for disk in dpraid_disks if not disk.bdf]
    if missing:
        log.write("No BDF mapping for dpraid disks: " + ", ".join(missing))


def drives_expr(group):
    dids = [disk.did for disk in group]
    if any(did is None for did in dids):
        raise AssertionError("Missing DID for RAID drive group")
    dids = sorted(dids)
    if len(dids) == 1:
        return str(dids[0])
    if dids == list(range(dids[0], dids[-1] + 1)):
        return f"{dids[0]}-{dids[-1]}"
    return ",".join(str(did) for did in dids)


def usable_capacity_gb(raid_level, disk_count, min_size_gb):
    if raid_level == 0:
        return min_size_gb * disk_count
    if raid_level == 1:
        return min_size_gb
    if raid_level == 10:
        return min_size_gb * (disk_count // 2)
    if raid_level == 50:
        span = 3
        spans = disk_count // span
        return min_size_gb * spans * (span - 1)
    if raid_level == 5:
        return min_size_gb * (disk_count - 1)
    raise AssertionError(f"Unsupported RAID level: {raid_level}")


def vd_size_gb_for_raid(raid_level, group, reserve_percent=Decimal("0")):
    min_size = min(disk.size_gb for disk in group)
    size = (usable_capacity_gb(raid_level, len(group), min_size) / Decimal(4)).to_integral_value(
        rounding=ROUND_FLOOR
    )
    if reserve_percent:
        size = (size * (Decimal("100") - reserve_percent) / Decimal("100")).to_integral_value(
            rounding=ROUND_FLOOR
        )
    if size <= 0:
        raise AssertionError(
            f"Invalid RAID{raid_level} VD size calculated from group: {group}"
        )
    return int(size)


def vd_size_gb(group, reserve_percent=Decimal("0")):
    return vd_size_gb_for_raid(5, group, reserve_percent)


def vd_size(group):
    return f"{vd_size_gb(group)}GB"


def cleanup_created_vds(before_ids, log):
    after_ids = set(parse_dpraid_virtual_ids(show_virtual_devices(log)))
    for index in sorted(after_ids - before_ids):
        run_cmd(["dpraid", f"/c0/v{index}", "delete"], log, check=False)


def create_raid_vds(group_specs, log, logical_block_size=DEFAULT_LOGICAL_BLOCK_SIZE):
    logical_block_size = resolve_logical_block_size(logical_block_size)
    for group, raid_level in group_specs:
        expr = drives_expr(group)
        size_gb = vd_size_gb_for_raid(raid_level, group, VD_SIZE_RESERVE_PERCENT)
        for attempt in range(1, VD_SIZE_RETRY_LIMIT + 1):
            before_ids = set(parse_dpraid_virtual_ids(show_virtual_devices(log)))
            failed_result = None
            for _ in range(VDS_PER_GROUP):
                result = run_cmd(
                    vd_create_cmd(expr, size_gb, logical_block_size, raid_level=raid_level),
                    log,
                    check=False,
                )
                if result.returncode != 0:
                    failed_result = result
                    break
            if failed_result is None:
                break
            cleanup_created_vds(before_ids, log)
            output = failed_result.stdout or ""
            if "Cannot allocate memory" not in output:
                raise AssertionError(
                    f"Command failed rc={failed_result.returncode}: "
                    f"{' '.join(vd_create_cmd(expr, size_gb, logical_block_size, raid_level=raid_level))}"
                )
            if attempt == VD_SIZE_RETRY_LIMIT:
                raise AssertionError(
                    f"Cannot create RAID{raid_level} VDs after {VD_SIZE_RETRY_LIMIT} attempts: "
                    f"drives={expr}, last Size={size_gb}GB"
                )
            step = max(1, (size_gb * int(VD_SIZE_RETRY_STEP_PERCENT) // 100))
            next_size_gb = size_gb - step
            if next_size_gb <= 0:
                raise AssertionError(
                    f"Cannot create RAID{raid_level} VDs: next Size would be {next_size_gb}GB after allocation failure: "
                    f"drives={expr}, last Size={size_gb}GB"
                )
            log.write(
                f"Retry RAID{raid_level} VD creation with smaller size after allocation failure: "
                f"drives={expr}, {size_gb}GB -> {next_size_gb}GB"
            )
            size_gb = next_size_gb


def create_raid5_vds(groups, log, logical_block_size=DEFAULT_LOGICAL_BLOCK_SIZE):
    create_raid_vds([(group, 5) for group in groups], log, logical_block_size=logical_block_size)


def dp_vd_devices(log):
    result = run_cmd(["lsblk", "-dn", "-o", "NAME,TYPE"], log, check=True)
    devices = []
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "disk" and re.fullmatch(r"dp\d+-vd\d+", parts[0]):
            devices.append(parts[0])
    log.write(f"Detected VD block devices: {devices}")
    return devices


def verify_vd_count(log, expected=8):
    devices = dp_vd_devices(log)
    if len(devices) != expected:
        raise AssertionError(f"Expected {expected} VD block devices, got {len(devices)}: {devices}")
    return devices


def expected_degraded_vd_count(group_specs):
    return sum(VDS_PER_GROUP for spec in group_specs if spec.raid_level != 0)


def prepare_multi_raid_vds(log, logical_block_size=None):
    logical_block_size = resolve_logical_block_size(logical_block_size)
    delete_existing_vds(log)
    delete_existing_pds(log)
    nvme_inventory_disks = nvme_inventory(log)
    for disk in nvme_inventory_disks:
        if disk.size_gb > 0:
            query_bdf(disk, log)
    nvme_disks = discover_nvme_data_disks(log, nvme_inventory_disks)
    if len(nvme_disks) < MIN_MULTI_RAID_DISKS:
        raise AssertionError(
            f"Need at least {MIN_MULTI_RAID_DISKS} non-system NVMe disks, got {len(nvme_disks)}"
        )
    add_physical_disks(nvme_disks, log)
    physical_output = show_physical_devices(log)
    disks = []
    for disk in parse_dpraid_physical_devices(physical_output):
        if is_excluded_nvme_model(disk.model):
            log.write(f"Skip excluded dpraid physical model: DID{disk.did} {disk.model}")
            continue
        disks.append(disk)
    if len(disks) < MIN_MULTI_RAID_DISKS:
        raise AssertionError(
            f"Need at least {MIN_MULTI_RAID_DISKS} dpraid physical disks, got {len(disks)}"
        )
    apply_bdf_from_nvme_inventory(disks, nvme_inventory_disks, log)
    log.write("Assigned DID by dpraid show: " + ", ".join(f"{d.namespace}->DID{d.did}" for d in disks))
    group_specs = partition_disks_for_multi_raid(disks)
    log.write(
        "Multi-RAID disk groups: "
        + " | ".join(
            f"{spec.label}({','.join(f'DID{d.did}' for d in spec.disks)})"
            for spec in group_specs
        )
    )
    log.write(f"Create multi-RAID VDs with LogicalBlockSize={logical_block_size}")
    create_raid_vds(
        [(spec.disks, spec.raid_level) for spec in group_specs],
        log,
        logical_block_size=logical_block_size,
    )
    verify_vd_count(log, expected=MULTI_RAID_VD_COUNT)
    vd_output = show_virtual_devices(log)
    return disks, group_specs, vd_output


def prepare_basic_raid5_vds(log, logical_block_size=None):
    logical_block_size = resolve_logical_block_size(logical_block_size)
    delete_existing_vds(log)
    delete_existing_pds(log)
    nvme_inventory_disks = nvme_inventory(log)
    for disk in nvme_inventory_disks:
        if disk.size_gb > 0:
            query_bdf(disk, log)
    nvme_disks = discover_nvme_data_disks(log, nvme_inventory_disks)
    add_physical_disks(nvme_disks, log)
    physical_output = show_physical_devices(log)
    disks = []
    for disk in parse_dpraid_physical_devices(physical_output):
        if is_excluded_nvme_model(disk.model):
            log.write(f"Skip excluded dpraid physical model: DID{disk.did} {disk.model}")
            continue
        disks.append(disk)
    if len(disks) < 2:
        raise AssertionError(f"Need at least 2 dpraid physical disks, got {len(disks)}")
    apply_bdf_from_nvme_inventory(disks, nvme_inventory_disks, log)
    log.write("Assigned DID by dpraid show: " + ", ".join(f"{d.namespace}->DID{d.did}" for d in disks))
    groups = split_groups(disks)
    log.write("Disk groups: " + " | ".join(",".join(f"DID{d.did}" for d in group) for group in groups))
    log.write(f"Create RAID5 VDs with LogicalBlockSize={logical_block_size}")
    create_raid5_vds(groups, log, logical_block_size=logical_block_size)
    verify_vd_count(log, expected=8)
    vd_output = show_virtual_devices(log)
    return disks, groups, vd_output


def slot_from_bdf(bdf, log):
    pci_addr = bdf.rsplit(".", 1)[0]
    result = run_cmd(f"lspci -s {pci_addr} -vvvv | grep -i slot", log, check=True, shell=True)
    match = re.search(r"(?:Physical Slot|Slot)[^0-9]*([0-9]+)", result.stdout, re.IGNORECASE)
    if not match:
        raise AssertionError(f"Cannot parse PCI slot from BDF {bdf}: {result.stdout}")
    return match.group(1)


def drop_pci_disk(bdf, log, remove_settle_seconds=1, rescan_settle_seconds=2):
    """Simulate disk drop via PCI hot-remove, then rescan to bring the device back.

    Uses /sys/bus/pci/devices/<bdf>/remove + pci rescan on both QEMU and physical hosts.
    Slot power sysfs (/sys/bus/pci/slots/*/power) is platform-specific and often not writable.
    """
    remove_path = f"/sys/bus/pci/devices/{bdf}/remove"
    if not Path(remove_path).exists():
        raise AssertionError(f"PCI device sysfs missing for BDF {bdf}: {remove_path}")
    run_cmd(f"echo 1 > {remove_path}", log, check=True, shell=True)
    run_cmd(["sleep", str(remove_settle_seconds)], log, check=True)
    run_cmd("echo 1 > /sys/bus/pci/rescan", log, check=True, shell=True)
    run_cmd(["sleep", str(rescan_settle_seconds)], log, check=True)


def degrade_non_raid0_groups(group_specs, log):
    non_raid0_groups = [spec.disks for spec in group_specs if spec.raid_level != 0]
    if not non_raid0_groups:
        raise AssertionError("No non-RAID0 groups available for degradation")
    log.write(
        "Degrade non-RAID0 groups: "
        + ", ".join(
            f"raid{spec.raid_level}({','.join(f'DID{d.did}' for d in spec.disks)})"
            for spec in group_specs
            if spec.raid_level != 0
        )
    )
    power_cycle_one_disk_per_group(non_raid0_groups, log)


def power_cycle_one_disk_per_group(groups, log):
    selected = []
    rng = random.SystemRandom()
    for group in groups:
        candidates = [disk for disk in group if disk.bdf and not is_excluded_nvme_model(disk.model)]
        if not candidates:
            raise AssertionError(
                "Cannot power-cycle group without BDF mapping: "
                + ",".join(f"DID{disk.did}:{disk.sn}" for disk in group)
            )
        selected.append(rng.choice(candidates))
    for disk in selected:
        log.write(f"PCI drop/rescan {disk.namespace} BDF {disk.bdf}")
        drop_pci_disk(disk.bdf, log)
        log.write(f"PCI drop/rescan done for {disk.namespace} BDF {disk.bdf}")


def verify_all_vds_degraded(log, expected=8):
    output = show_virtual_devices(log)
    degraded = len(re.findall(r"\bDegr\b", output, re.IGNORECASE))
    if degraded < expected:
        raise AssertionError(f"Expected at least {expected} degraded VDs, got {degraded}")
