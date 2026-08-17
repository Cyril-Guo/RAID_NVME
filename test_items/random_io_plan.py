"""Build 16 non-overlapping random FIO models with 4k-aligned blocks and crc verify."""
from __future__ import annotations

import os
import random
import re
import subprocess

LBA_SIZE = 4096
MODEL_COUNT = 16
SLICE_PERCENT = 6
VERIFY_TYPE = "crc32c"
_DRAID_VD = re.compile(r"^dp[0-9]+-vd[0-9]+$")
CSV_HEADER = (
    "Block_Size,Random_Percentage,Read_Percentage,Queue_Depth,"
    "Run_Time(ss:mm:hh:dd),Number_of_Jobs,Offset,IO_Size,Verify_Mode,Verify_Type"
)

BLOCK_SIZES = ("4k", "8k", "16k", "32k", "64k", "128k", "256k", "512k", "1m")
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
            "PARALLEL WRITE, then PARALLEL VERIFY"
        )
    peak = peak_qd(plan)
    lines.extend(
        [
            "-" * 96,
            (
                f" 16 models run together. Per-disk peak QD = {peak} "
                "(sum of model QDs); regions do not overlap."
            ),
            " Block sizes are 4k multiples. WRITE all slices first, then VERIFY all slices.",
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
    for model in plan["models"]:
        rows.append(_csv_row(model, "WRITE"))
    for model in plan["models"]:
        rows.append(_csv_row(model, "VERIFY"))
    rows.append("End,,,,,,,,,")
    return "\n".join(rows) + "\n"


def write_plan_csv(plan, path):
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(plan_to_csv(plan))
    return path


def list_test_disks():
    raw = os.environ.get("FIO_DISKS", "").strip()
    if raw:
        return [
            part.strip().removeprefix("/dev/")
            for part in raw.replace(",", " ").split()
            if part.strip()
        ]
    try:
        result = subprocess.run(
            ["lsblk", "-dn", "-o", "NAME,TYPE"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return []
    disks = []
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "disk" and _DRAID_VD.match(parts[0]):
            disks.append(parts[0])
    return sorted(disks)


def _job_rw(model):
    lines = [f"rw={model['name']}"]
    if model["name"] in ("randrw", "rw"):
        lines.append(f"rwmixread={model['read_pct']}")
    return lines


def plan_to_fio_job(plan, disks, phase):
    if phase not in ("WRITE", "VERIFY"):
        raise ValueError(phase)
    lines = [
        "# random_io parallel FIO job",
        f"# seed={plan['seed']} phase={phase} models={len(plan['models'])} disks={','.join(disks)}",
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
    if phase == "WRITE":
        lines.append("do_verify=0")
    else:
        lines.append("verify_only=1")
    lines.append("")
    for disk in disks:
        for model in plan["models"]:
            name = f"m{model['id']:02d}_{model['name']}_{model['bs']}_qd{model['iodepth']}_{disk}"
            lines.extend(
                [
                    f"[{name}]",
                    f"filename=/dev/{disk}",
                    *_job_rw(model),
                    f"bs={model['bs']}",
                    f"iodepth={model['iodepth']}",
                    f"numjobs={model['numjobs']}",
                    f"offset={model['offset_pct']}%",
                    f"size={model['size_pct']}%",
                    "",
                ]
            )
    return "\n".join(lines).rstrip() + "\n"


def write_fio_job(plan, disks, path, phase):
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(plan_to_fio_job(plan, disks, phase))
    return path


def regions_overlap(models):
    spans = sorted(
        (item["offset_pct"], item["offset_pct"] + item["size_pct"]) for item in models
    )
    for index in range(1, len(spans)):
        if spans[index][0] < spans[index - 1][1]:
            return True
    return False
