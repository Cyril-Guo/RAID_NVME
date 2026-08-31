"""Build 16 non-overlapping FIO models: sequential FILL, mixed STRESS, sequential VERIFY.

Design goals:
- Stress coverage (many bs / rw / QD) AND data consistency (crc32c) every round.
- FILL / STRESS / VERIFY all use the *same model bs* so verify headers match.
- Each round scatters 16 small windows across the whole disk (not packed at LBA 0).
- Single external knob: RANDOM_IO_DURATION (wall clock). Slice/STRESS/loops are internal.
"""
from __future__ import annotations

import hashlib
import os
import random
import re
import subprocess

LBA_SIZE = 512
# Internal pacing (not exposed in test_items.txt).
DEFAULT_STRESS_RUNTIME = 45
DEFAULT_DURATION_SECONDS = 12 * 3600
DURATION_ENV = "RANDOM_IO_DURATION"
MODEL_COUNT = 16
VERIFY_TYPE = "crc32c"
PHASES = ("FILL", "STRESS", "VERIFY")
# FILL/VERIFY: high QD sequential for wall-clock; STRESS keeps per-model QD.
PREP_IODEPTH = 64
# Adaptive slice: target similar FILL IO count across tiny and large bs.
TARGET_FILL_IOS = 32768
MIN_SLICE_BYTES = 16 * 1024**2
MAX_SLICE_BYTES = 256 * 1024**2
_DRAID_VD = re.compile(r"^dp[0-9]+-vd[0-9]+$")
CSV_HEADER = (
    "Disk,Model_ID,Model,Block_Size,Queue_Depth,Offset_Bytes,Size_Bytes,"
    "Random_Percentage,Read_Percentage,Verify_Mode,Verify_Type"
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


def _align_down(value: int, align: int) -> int:
    if align <= 0:
        return value
    return (value // align) * align


def _align_up(value: int, align: int) -> int:
    if align <= 0:
        return value
    return ((value + align - 1) // align) * align


def adaptive_slice_bytes(bs_label: str) -> int:
    """Pick a per-model slice so tiny-bs FILL stays bounded for many 12h rounds."""
    bs = block_size_bytes(bs_label)
    raw = TARGET_FILL_IOS * bs
    size = max(MIN_SLICE_BYTES, min(MAX_SLICE_BYTES, raw))
    size = _align_down(size, bs)
    if size < bs:
        size = bs
    return size


def parse_duration_seconds(raw=None) -> int:
    """Parse RANDOM_IO_DURATION: 12h / 720m / 43200s / 43200. Default 12h."""
    if raw is None:
        raw = os.environ.get(DURATION_ENV, "").strip()
    text = (raw or "").strip().lower()
    if not text:
        return DEFAULT_DURATION_SECONDS
    if text.endswith("h"):
        return max(1, int(float(text[:-1]) * 3600))
    if text.endswith("m"):
        return max(1, int(float(text[:-1]) * 60))
    if text.endswith("s"):
        return max(1, int(float(text[:-1])))
    return max(1, int(float(text)))


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
        seed = random.SystemRandom().randint(1, 2**31 - 1)
    rng = random.Random(seed)
    pool = _candidates()
    rng.shuffle(pool)
    models = []
    for index, spec in enumerate(pool[:MODEL_COUNT], start=1):
        models.append(
            {
                "id": index,
                "name": spec["name"],
                "bs": spec["bs"],
                "iodepth": spec["iodepth"],
                "numjobs": 1,
                "random_pct": spec["random_pct"],
                "read_pct": spec["read_pct"],
                "slice_bytes": adaptive_slice_bytes(spec["bs"]),
                "verify": VERIFY_TYPE,
            }
        )
    return {"seed": seed, "lba_size": LBA_SIZE, "models": models}


def format_plan(plan, disk_sizes=None):
    lines = [
        "=" * 108,
        " Random IO FIO Plan",
        (
            f" seed={plan['seed']}   models={len(plan['models'])}   "
            f"LBA={plan['lba_size']}   sizing=adaptive "
            f"{MIN_SLICE_BYTES // 1024**2}-{MAX_SLICE_BYTES // 1024**2}MiB   "
            f"verify={VERIFY_TYPE}"
        ),
        (
            " Each round covers 16 scattered windows only (not full-disk); "
            "multi-round coverage accumulates statistically."
        ),
        "-" * 108,
        f" {'ID':>3}  {'Model':<10} {'BS':<6} {'QD':>4} {'Slice':>10} "
        f"{'Rnd%':>5} {'Rd%':>4}  Phases",
        "-" * 108,
    ]
    for model in plan["models"]:
        lines.append(
            f" {model['id']:>3}  {model['name']:<10} {model['bs']:<6} {model['iodepth']:>4} "
            f"{_human_bytes(model['slice_bytes']):>10} {model['random_pct']:>5} {model['read_pct']:>4}  "
            "FILL, then STRESS, then VERIFY (same bs)"
        )
    peak = peak_qd(plan)
    lines.extend(
        [
            "-" * 108,
            (
                f" Per-disk peak STRESS QD = {peak} (sum of model QDs); "
                "16 windows are randomly scattered across the whole disk (non-overlapping)."
            ),
        ]
    )
    if disk_sizes:
        lines.append("-" * 108)
        lines.append(
            f" {'Disk':<12} {'ID':>3}  {'Model':<10} {'BS':<6} "
            f"{'Offset':>14} {'Size':>10}"
        )
        lines.append("-" * 108)
        for disk, disk_size_bytes in sorted(disk_sizes.items()):
            for place in layout_models_on_disk(plan, disk_size_bytes, disk_key=disk):
                model = place["model"]
                lines.append(
                    f" {disk:<12} {model['id']:>3}  {model['name']:<10} {model['bs']:<6} "
                    f"{place['offset_bytes']:>14} {_human_bytes(place['size_bytes']):>10}"
                )
    lines.extend(
        [
            "-" * 108,
            " FILL sequential-writes every LBA in each window with crc32c headers (model bs).",
            " STRESS runs the 16 models in parallel (writes keep crc32c headers at model bs).",
            " VERIFY sequential-reads the same windows at the same bs; failures are consistency bugs.",
            "=" * 108,
        ]
    )
    return "\n".join(lines)


def _human_bytes(num: int) -> str:
    for unit, scale in (("GiB", 1024**3), ("MiB", 1024**2), ("KiB", 1024)):
        if num >= scale and num % scale == 0:
            return f"{num // scale}{unit}"
    return f"{num}B"


def peak_qd(plan):
    return sum(int(model["iodepth"]) for model in plan["models"])


def format_consistency_result(round_idx: int, disk_count: int, passed: bool) -> str:
    status = "PASS" if passed else "FAIL"
    return (
        f"[RANDOM_IO round {round_idx}] DATA_CONSISTENCY={status} "
        f"disks={disk_count} per_disk_models={MODEL_COUNT} "
        f"total_jobs={disk_count * MODEL_COUNT} verify={VERIFY_TYPE}"
    )


def plan_to_csv(plan, disk_sizes=None):
    """CSV uses real byte offsets when disk_sizes is provided."""
    rows = [CSV_HEADER]
    if not disk_sizes:
        for phase in PHASES:
            for model in plan["models"]:
                rows.append(
                    ",".join(
                        [
                            "",
                            str(model["id"]),
                            model["name"],
                            model["bs"],
                            str(model["iodepth"]),
                            "",
                            str(model["slice_bytes"]),
                            str(model["random_pct"]),
                            str(model["read_pct"]),
                            phase,
                            model["verify"],
                        ]
                    )
                )
    else:
        for disk, disk_size_bytes in sorted(disk_sizes.items()):
            placements = layout_models_on_disk(plan, disk_size_bytes, disk_key=disk)
            for phase in PHASES:
                for place in placements:
                    model = place["model"]
                    rows.append(
                        ",".join(
                            [
                                disk,
                                str(model["id"]),
                                model["name"],
                                model["bs"],
                                str(model["iodepth"]),
                                str(place["offset_bytes"]),
                                str(place["size_bytes"]),
                                str(model["random_pct"]),
                                str(model["read_pct"]),
                                phase,
                                model["verify"],
                            ]
                        )
                    )
    rows.append("End,,,,,,,,,,")
    return "\n".join(rows) + "\n"


def write_plan_csv(plan, path, disk_sizes=None):
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(plan_to_csv(plan, disk_sizes=disk_sizes))
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


def _model_slice_bytes(model) -> tuple[int, int]:
    """Return (bs_bytes, size_bytes) for a model (adaptive only)."""
    bs = block_size_bytes(model["bs"])
    size_bytes = _align_down(int(model["slice_bytes"]), bs) or bs
    return bs, size_bytes


def _layout_rng_seed(plan_seed, disk_size_bytes: int, disk_key: str) -> int:
    raw = f"{plan_seed}:{disk_size_bytes}:{disk_key}".encode()
    return int(hashlib.sha256(raw).hexdigest()[:16], 16)


def layout_models_on_disk(plan, disk_size_bytes: int, disk_key: str = "") -> list[dict]:
    """
    Return [{model, offset_bytes, size_bytes}, ...] scattered across the disk.

    Windows are non-overlapping, bs-aligned, and placed randomly over the full
    capacity (deterministic from plan seed + disk). FILL/STRESS/VERIFY share the
    same layout for a given plan/disk.
    """
    if disk_size_bytes < LBA_SIZE:
        raise ValueError(f"Invalid disk size for layout: {disk_size_bytes} bytes")

    models = list(plan["models"])
    sized = []
    total_payload = 0
    for model in models:
        bs, size_bytes = _model_slice_bytes(model)
        sized.append((model, bs, size_bytes))
        total_payload += size_bytes

    if total_payload > disk_size_bytes:
        raise ValueError(
            f"Disk too small for random_io layout: disk={disk_size_bytes}B, "
            f"need_payload={total_payload}B for {len(sized)} windows. "
            "Enlarge the VD or reduce MODEL_COUNT/slice constants."
        )

    rng = random.Random(_layout_rng_seed(plan["seed"], disk_size_bytes, disk_key))
    rng.shuffle(sized)

    # Free intervals as half-open [start, end).
    free: list[tuple[int, int]] = [(0, disk_size_bytes)]
    placements = []

    for model, bs, size_bytes in sized:
        candidates = []
        for idx, (start, end) in enumerate(free):
            aligned_start = _align_up(start, bs)
            if aligned_start + size_bytes > end:
                continue
            max_start = _align_down(end - size_bytes, bs)
            if max_start < aligned_start:
                continue
            steps = ((max_start - aligned_start) // bs) + 1
            candidates.append((idx, aligned_start, steps))

        if not candidates:
            raise ValueError(
                f"Disk too fragmented for random_io window: disk={disk_size_bytes}B, "
                f"model={model['id']} bs={model['bs']} size={size_bytes}B. "
                "Enlarge the VD."
            )

        # Prefer larger holes so windows spread across the disk.
        idx, aligned_start, steps = rng.choices(
            candidates, weights=[item[2] for item in candidates], k=1
        )[0]
        offset_bytes = aligned_start + rng.randrange(steps) * bs
        end_bytes = offset_bytes + size_bytes

        start, end = free.pop(idx)
        parts = []
        if start < offset_bytes:
            parts.append((start, offset_bytes))
        if end_bytes < end:
            parts.append((end_bytes, end))
        free[idx:idx] = parts

        placements.append(
            {
                "model": model,
                "offset_bytes": offset_bytes,
                "size_bytes": size_bytes,
            }
        )

    placements.sort(key=lambda item: (item["offset_bytes"], item["model"]["id"]))
    return placements


def plan_to_fio_job(plan, disk_sizes, phase, stress_runtime=None):
    if phase not in PHASES:
        raise ValueError(phase)
    if stress_runtime is None:
        stress_runtime = DEFAULT_STRESS_RUNTIME
    lines = [
        "# random_io parallel FIO job",
        f"# seed={plan['seed']} phase={phase} models={len(plan['models'])} disks={','.join(sorted(disk_sizes.keys()))}",
        "[global]",
        "ioengine=libaio",
        "direct=1",
        "refill_buffers",
        "norandommap",
        "randrepeat=0",
        # Avoid false crc failures when high QD issues overlapping IOs on one job.
        "serialize_overlap=1",
        f"verify={VERIFY_TYPE}",
        "verify_fatal=1",
        "verify_dump=1",
        "group_reporting",
    ]
    if phase == "VERIFY":
        lines.append("verify_only=1")
    else:
        lines.append("do_verify=0")
    # STRESS runs for a fixed wall-clock duration so total test time stays predictable.
    if phase == "STRESS":
        lines += [f"runtime={stress_runtime}", "time_based=1"]
    lines.append("")
    for disk, disk_size_bytes in disk_sizes.items():
        for place in layout_models_on_disk(plan, disk_size_bytes, disk_key=disk):
            model = place["model"]
            name = f"m{model['id']:02d}_{model['name']}_{model['bs']}_qd{model['iodepth']}_{disk}"
            # Same bs for FILL/STRESS/VERIFY so crc32c headers stay valid end-to-end.
            fio_bs = model["bs"]
            iodepth = model["iodepth"] if phase == "STRESS" else PREP_IODEPTH
            lines.extend(
                [
                    f"[{name}]",
                    f"filename=/dev/{disk}",
                    *_phase_rw(model, phase),
                    f"bs={fio_bs}",
                    f"iodepth={iodepth}",
                    f"numjobs={model['numjobs']}",
                    f"offset={place['offset_bytes']}B",
                    f"size={place['size_bytes']}B",
                    "",
                ]
            )
    return "\n".join(lines).rstrip() + "\n"


def write_fio_job(plan, disk_sizes, path, phase, stress_runtime=None):
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(plan_to_fio_job(plan, disk_sizes, phase, stress_runtime=stress_runtime))
    return path


def regions_overlap_bytes(placements):
    spans = sorted(
        (item["offset_bytes"], item["offset_bytes"] + item["size_bytes"]) for item in placements
    )
    for index in range(1, len(spans)):
        if spans[index][0] < spans[index - 1][1]:
            return True
    return False
