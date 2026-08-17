"""Build 16 non-overlapping random FIO models with 4k-aligned blocks and crc verify."""
from __future__ import annotations

import os
import random

LBA_SIZE = 4096
MODEL_COUNT = 16
SLICE_PERCENT = 6
VERIFY_TYPE = "crc32c"
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
            "WRITE then VERIFY"
        )
    lines.extend(
        [
            "-" * 96,
            " Regions do not overlap. Jobs=1 keeps verify consistent; QD is the concurrency.",
            " Block sizes are 4k multiples. After all WRITE slices finish, VERIFY reads them back.",
            "=" * 96,
        ]
    )
    return "\n".join(lines)


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


def regions_overlap(models):
    spans = sorted(
        (item["offset_pct"], item["offset_pct"] + item["size_pct"]) for item in models
    )
    for index in range(1, len(spans)):
        if spans[index][0] < spans[index - 1][1]:
            return True
    return False
