"""Build 16 non-overlapping FIO models: sequential FILL, mixed STRESS, sequential VERIFY."""
from __future__ import annotations

import os
import random
import re
import subprocess

LBA_SIZE = 512
FILL_BLOCK_SIZE_LABEL = "256k"
MODEL_COUNT = 16
SLICE_PERCENT = 6
VERIFY_TYPE = "crc32c"
PHASES = ("FILL", "STRESS", "VERIFY")
_DRAID_VD = re.compile(r"^dp[0-9]+-vd[0-9]+$")
CSV_HEADER = (
    "Block_Size,Random_Percentage,Read_Percentage,Queue_Depth,"
    "Run_Time(ss:mm:hh:dd),Number_of_Jobs,Offset,IO_Size,Verify_Mode,Verify_Type"
)

BLOCK_SIZES = (
    "512",
    "1k",
    "2k",
    "3k",
    "4k",
    "5k",
    "6k",
    "8k",
    "12k",
    "16k",
    "20k",
    "24k",
    "32k",
    "48k",
    "64k",
    "96k",
    "128k",
    "192k",
    "256k",
    "384k",
    "512k",
    "768k",
    "1m",
    "2m",
    "4m",
    "8m",
    "16m",
)
RW_CHOICES = (
    {"random_pct": 100, "read_pct": 0, "name": "randwrite"},
    {"random_pct": 0, "read_pct": 0, "name": "write"},
    {"random_pct": 100, "read_pct": 30, "name": "randrw"},
    {"random_pct": 100, "read_pct": 50, "name": "randrw"},
    {"random_pct": 100, "read_pct": 70, "name": "randrw"},
    {"random_pct": 0, "read_pct": 50, "name": "rw"},
)
IODEPTHS = (1, 4, 8, 16, 32, 64, 128, 256)


def block_size_bytes(label):
    text = label.strip().lower()
    if text.endswith("k"):
        return int(text[:-1]) * 1024
    if text.endswith("m"):
        return int(text[:-1]) * 1024 * 1024
    return int(text)


def _candidates():
    items = []
    for block_size in BLOCK_SIZES:
        for rw in RW_CHOICES:
            for iodepth in IODEPTHS:
                items.append(
                    {
                        "bs": block_size,
                        "iodepth": iodepth,
                        "random_pct": rw["random_pct"],
                        "read_pct": rw["read_pct"],
                        "name": rw["name"],
                    }
                )
    return items


def generate_random_io_plan(seed=None):
    if seed is None:
        raw = os.environ.get("RANDOM_IO_SEED", "").strip()
        seed = int(raw) if raw else random.SystemRandom().randint(1, 2**31 - 1)
    rng = random.Random(seed)
    pool = _candidates()
    rng.shuffle(pool)
    slices = list(range(MODEL_COUNT))
    rng.shuffle(slices)
    models = []
    for index, (spec, slice_id) in enumerate(zip(pool[:MODEL_COUNT], slices), start=1):
        models.append(
            {
                "id": index,
                "name": spec["name"],
                "bs": spec["bs"],
                "iodepth": spec["iodepth"],
                "numjobs": 1,
                "random_pct": spec["random_pct"],
                "read_pct": spec["read_pct"],
                "offset_pct": slice_id * SLICE_PERCENT,
                "size_pct": SLICE_PERCENT,
                "verify": VERIFY_TYPE,
            }
        )
    models.sort(key=lambda item: (item["offset_pct"], item["id"]))
    for index, model in enumerate(models, start=1):
        model["id"] = index
    return {"seed": seed, "lba_size": LBA_SIZE, "models": models}


def format_plan(plan):
    lines = [
        "=" * 96,
        " Random IO FIO Plan",
        (
            f" seed={plan['seed']}   models={len(plan['models'])}   "
            f"LBA={plan['lba_size']}   slice={SLICE_PERCENT}%   verify={VERIFY_TYPE}"
        ),
        "-" * 96,
        f" {'ID':>3}  {'Model':<10} {'BS':<6} {'QD':>4} {'Jobs':>4} "
        f"{'Offset':>7} {'Size':>5} {'Rnd%':>5} {'Rd%':>4}  Phases",
        "-" * 96,
    ]
    for model in plan["models"]:
        lines.append(
            f" {model['id']:>3}  {model['name']:<10} {model['bs']:<6} {model['iodepth']:>4} "
            f"{model['numjobs']:>4} {str(model['offset_pct']) + '%':>7} "
            f"{str(model['size_pct']) + '%':>5} {model['random_pct']:>5} {model['read_pct']:>4}  "
            "FILL, then STRESS, then VERIFY"
        )
    peak = peak_qd(plan)
    lines.extend(
        [
            "-" * 96,
            (
                f" Per-disk peak QD = {peak} (sum of model QDs); regions do not overlap."
            ),
            " FILL sequential-writes every LBA in each slice with crc32c headers.",
            " STRESS then runs the 16 models in parallel (writes keep crc32c headers).",
            " VERIFY sequential-reads the same slices; failures are disk consistency, not unwritten holes.",
            "=" * 96,
        ]
    )
    return "\n".join(lines)


def peak_qd(plan):
    return sum(int(model["iodepth"]) for model in plan["models"])


def _csv_row(model, verify_mode):
    return ",".join(
        [
            model["bs"],
            str(model["random_pct"]),
            str(model["read_pct"]),
            str(model["iodepth"]),
            "0",
            str(model["numjobs"]),
            f"{model['offset_pct']}%",
            f"{model['size_pct']}%",
            verify_mode,
            model["verify"],
        ]
    )


def plan_to_csv(plan):
    rows = [CSV_HEADER]
    for phase in PHASES:
        for model in plan["models"]:
            rows.append(_csv_row(model, phase))
    rows.append("End,,,,,,,,,")
    return "\n".join(rows) + "\n"


def write_plan_csv(plan, path):
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(plan_to_csv(plan))
    return path


def list_test_disks():
    """
    Return {disk_name: size_bytes} for dp*-vd* devices.

    When FIO_DISKS is set, only those disks are included (still tries to detect SIZE).
    """
    desired_raw = os.environ.get("FIO_DISKS", "").strip()
    desired = None
    if desired_raw:
        desired = {
            part.strip().removeprefix("/dev/")
            for part in desired_raw.replace(",", " ").split()
            if part.strip()
        }

    try:
        # -b makes SIZE in bytes.
        result = subprocess.run(
            ["lsblk", "-dn", "-b", "-o", "NAME,TYPE,SIZE"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return {}

    disk_sizes: dict[str, int] = {}
    for line in (result.stdout or "").splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        name, typ, size_str = parts[0], parts[1], parts[2]
        # Safety: random_io should target only dp*-vd* VD devices.
        if not _DRAID_VD.match(name):
            continue
        if desired is not None and name not in desired:
            continue
        if desired is None and (typ != "disk" or not _DRAID_VD.match(name)):
            continue
        try:
            size_bytes = int(size_str)
        except ValueError:
            continue
        if size_bytes > 0:
            disk_sizes[name] = size_bytes

    return {k: disk_sizes[k] for k in sorted(disk_sizes.keys())}


def _job_rw(model):
    lines = [f"rw={model['name']}"]
    if model["name"] in ("randrw", "rw"):
        lines.append(f"rwmixread={model['read_pct']}")
    return lines


def _phase_rw(model, phase):
    if phase == "FILL":
        return ["rw=write"]
    if phase == "VERIFY":
        return ["rw=read"]
    return _job_rw(model)

def _slice_lba_for_disk(disk_size_bytes: int):
    total_lba = disk_size_bytes // LBA_SIZE
    if total_lba <= 0:
        raise ValueError(f"Invalid disk size for slice computation: {disk_size_bytes} bytes")
    slice_lba = int(total_lba * SLICE_PERCENT / 100)
    if slice_lba <= 0:
        raise ValueError(f"Slice too small: total_lba={total_lba}, slice_lba={slice_lba}")
    return total_lba, slice_lba


def plan_to_fio_job(plan, disk_sizes, phase):
    if phase not in PHASES:
        raise ValueError(phase)
    lines = [
        "# random_io parallel FIO job",
        f"# seed={plan['seed']} phase={phase} models={len(plan['models'])} disks={','.join(sorted(disk_sizes.keys()))}",
        "[global]",
        "ioengine=libaio",
        "direct=1",
        "refill_buffers",
        "norandommap",
        "randrepeat=0",
        f"verify={VERIFY_TYPE}",
        "verify_fatal=1",
        "verify_dump=1",
        "group_reporting",
    ]
    if phase == "VERIFY":
        lines.append("verify_only=1")
    else:
        lines.append("do_verify=0")
    lines.append("")
    for disk, disk_size_bytes in disk_sizes.items():
        _total_lba, slice_lba = _slice_lba_for_disk(disk_size_bytes)
        for model in plan["models"]:
            name = f"m{model['id']:02d}_{model['name']}_{model['bs']}_qd{model['iodepth']}_{disk}"
            # offset_pct/size_pct are kept for reporting, but we generate concrete offsets
            # in bytes to avoid percentage rounding issues across different bs.
            slice_id = int(model["offset_pct"] // SLICE_PERCENT)
            offset_lba = slice_id * slice_lba
            size_lba = slice_lba
            offset_bytes = offset_lba * LBA_SIZE
            size_bytes = size_lba * LBA_SIZE
            # FILL is only an initialization pass; using a larger sequential write block improves speed
            # without changing the slice coverage (offset/size are still identical per phase).
            fio_bs = FILL_BLOCK_SIZE_LABEL if phase == "FILL" else model["bs"]
            lines.extend(
                [
                    f"[{name}]",
                    f"filename=/dev/{disk}",
                    *_phase_rw(model, phase),
                    f"bs={fio_bs}",
                    f"iodepth={model['iodepth']}",
                    f"numjobs={model['numjobs']}",
                    f"offset={offset_bytes}B",
                    f"size={size_bytes}B",
                    "",
                ]
            )
    return "\n".join(lines).rstrip() + "\n"


def write_fio_job(plan, disk_sizes, path, phase):
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(plan_to_fio_job(plan, disk_sizes, phase))
    return path


def regions_overlap(models):
    spans = sorted(
        (item["offset_pct"], item["offset_pct"] + item["size_pct"]) for item in models
    )
    for index in range(1, len(spans)):
        if spans[index][0] < spans[index - 1][1]:
            return True
    return False
