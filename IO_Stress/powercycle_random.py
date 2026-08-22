import argparse
import csv
import hashlib
import json
import os
import random
from dataclasses import asdict, dataclass
from typing import List, Optional

# Scattered windows per loop; FILL/STRESS before reboot, VERIFY after reboot.
WINDOW_COUNT = 5
WINDOW_BYTES = 128 * 1024 * 1024
DEFAULT_STRESS_RUNTIME = 45
FILL_VERIFY_IODEPTH = 64
MIN_BLOCK_BYTES = 512
MAX_BLOCK_BYTES = 16 * 1024 * 1024
ALIGNMENT_BYTES = 512
VERIFY_TYPE = "crc32c"
HEADER = [
    "Block_Size",
    "Random_Percentage",
    "Read_Percentage",
    "Queue_Depth",
    "Run_Time(ss:mm:hh:dd)",
    "Number_of_Jobs",
    "Offset",
    "Size",
    "Verify_Mode",
    "Verify_Type",
]
BLOCK_SIZES_BYTES = (
    512,
    1024,
    2048,
    3072,
    4096,
    6144,
    8192,
    16384,
    32768,
    65536,
    131072,
    262144,
    524288,
    1048576,
    2097152,
    4194304,
)
RW_CHOICES = (
    {"random_pct": 100, "read_pct": 0},
    {"random_pct": 100, "read_pct": 30},
    {"random_pct": 100, "read_pct": 50},
    {"random_pct": 100, "read_pct": 70},
    {"random_pct": 0, "read_pct": 50},
)
IODEPTHS = (1, 2, 4, 8, 16, 32)


@dataclass
class PowercycleModel:
    block_size: int
    queue_depth: int
    offset: int
    size: int
    verify_type: str = VERIFY_TYPE
    random_percentage: int = 0
    read_percentage: int = 0
    num_jobs: int = 1


def _align_down(value: int, align: int) -> int:
    if align <= 0:
        return value
    return (value // align) * align


def _align_up(value: int, align: int) -> int:
    if align <= 0:
        return value
    return ((value + align - 1) // align) * align


def _layout_seed(plan_seed: int, disk_size_bytes: int) -> int:
    raw = f"{plan_seed}:{disk_size_bytes}:powercycle".encode()
    return int(hashlib.sha256(raw).hexdigest()[:16], 16)


def _effective_window_count(disk_size_bytes: int) -> int:
    if disk_size_bytes < WINDOW_BYTES:
        return 1
    return min(WINDOW_COUNT, max(1, disk_size_bytes // WINDOW_BYTES))


def _window_size_bytes(block_size: int) -> int:
    size = _align_down(WINDOW_BYTES, block_size) or block_size
    return max(size, block_size)


def layout_windows(
    models: List[PowercycleModel],
    disk_size_bytes: int,
    plan_seed: int,
) -> List[PowercycleModel]:
    """Place non-overlapping windows across the disk (deterministic from plan_seed)."""
    if disk_size_bytes < ALIGNMENT_BYTES:
        raise ValueError(f"disk too small: {disk_size_bytes}")

    sized = [(model, model.block_size, model.size) for model in models]
    total_payload = sum(item[2] for item in sized)
    if total_payload > disk_size_bytes:
        raise ValueError(
            f"disk too small for {len(sized)} windows: need {total_payload}B, have {disk_size_bytes}B"
        )

    rng = random.Random(_layout_seed(plan_seed, disk_size_bytes))
    rng.shuffle(sized)

    free = [(0, disk_size_bytes)]
    placed: List[PowercycleModel] = []

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
                f"disk too fragmented for window bs={bs} size={size_bytes} on {disk_size_bytes}B disk"
            )

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

        placed.append(
            PowercycleModel(
                block_size=model.block_size,
                queue_depth=model.queue_depth,
                offset=offset_bytes,
                size=size_bytes,
                verify_type=model.verify_type,
                random_percentage=model.random_percentage,
                read_percentage=model.read_percentage,
                num_jobs=model.num_jobs,
            )
        )

    placed.sort(key=lambda item: item.offset)
    return placed


def generate_window_specs(
    disk_size_bytes: int,
    plan_seed: int,
    rng: Optional[random.Random] = None,
) -> List[PowercycleModel]:
    rng = rng or random.Random(plan_seed)
    count = _effective_window_count(disk_size_bytes)
    rw_pool = list(RW_CHOICES)
    rng.shuffle(rw_pool)

    specs: List[PowercycleModel] = []
    for index in range(count):
        block_size = rng.choice(BLOCK_SIZES_BYTES)
        if block_size > MAX_BLOCK_BYTES:
            block_size = MAX_BLOCK_BYTES
        size_bytes = _window_size_bytes(block_size)
        rw = rw_pool[index % len(rw_pool)]
        specs.append(
            PowercycleModel(
                block_size=block_size,
                queue_depth=rng.choice(IODEPTHS),
                offset=0,
                size=size_bytes,
                random_percentage=rw["random_pct"],
                read_percentage=rw["read_pct"],
            )
        )

    return layout_windows(specs, disk_size_bytes, plan_seed)


def model_to_row(
    model: PowercycleModel,
    verify_mode: str,
    *,
    stress_runtime: int = DEFAULT_STRESS_RUNTIME,
) -> list[str]:
    random_pct = model.random_percentage
    read_pct = model.read_percentage
    iodepth = model.queue_depth
    run_time = "0"

    if verify_mode == "FILL":
        random_pct = 0
        read_pct = 0
        iodepth = FILL_VERIFY_IODEPTH
    elif verify_mode == "VERIFY":
        random_pct = 0
        read_pct = 100
        iodepth = FILL_VERIFY_IODEPTH
    elif verify_mode == "STRESS":
        run_time = str(stress_runtime)
    elif verify_mode == "WRITE":
        # Legacy alias for FILL.
        random_pct = 0
        read_pct = 0
        iodepth = FILL_VERIFY_IODEPTH
        verify_mode = "FILL"

    return [
        str(model.block_size),
        str(random_pct),
        str(read_pct),
        str(iodepth),
        run_time,
        str(model.num_jobs),
        str(model.offset),
        str(model.size),
        verify_mode,
        model.verify_type,
    ]


def _pending_windows(state: dict) -> List[dict]:
    if not state.get("pending_verify"):
        return []
    windows = state.get("windows")
    if windows:
        return windows
    legacy = state.get("model")
    if legacy:
        return [legacy]
    return []


def load_state(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def write_state(path: str, payload: dict) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)


def build_plan(
    state: dict,
    current_loop: int,
    total_loops: int,
    min_disk_size_bytes: int,
    rng: Optional[random.Random] = None,
):
    rng = rng or random.Random()
    rows: list[list[str]] = []
    summary: list[str] = []

    pending = _pending_windows(state)
    if pending:
        for model_data in pending:
            model = PowercycleModel(**model_data)
            rows.append(model_to_row(model, "VERIFY"))
        summary.append(
            "verify previous windows: "
            + ", ".join(
                f"bs={m.block_size} off={m.offset} sz={m.size} qd={m.queue_depth}"
                for m in (PowercycleModel(**item) for item in pending)
            )
        )

    next_state = {"pending_verify": False, "windows": None, "plan_seed": None}
    if current_loop < total_loops:
        plan_seed = rng.randint(1, 2**31 - 1)
        windows = generate_window_specs(min_disk_size_bytes, plan_seed, rng=rng)
        for model in windows:
            rows.append(model_to_row(model, "FILL"))
        for model in windows:
            rows.append(model_to_row(model, "STRESS"))
        next_state = {
            "pending_verify": True,
            "plan_seed": plan_seed,
            "windows": [asdict(model) for model in windows],
        }
        summary.append(
            f"fill+stress {len(windows)} scattered windows (seed={plan_seed}, "
            f"stress={DEFAULT_STRESS_RUNTIME}s each)"
        )

    return rows, next_state, summary


def write_csv(path: str, rows: list[list[str]]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(HEADER)
        writer.writerows(rows)
        writer.writerow(["End", "", "", "", "", "", "", "", "", ""])


def command_plan(args: argparse.Namespace) -> int:
    rng = random.Random()
    state = load_state(args.state)
    rows, next_state, summary = build_plan(
        state=state,
        current_loop=args.current_loop,
        total_loops=args.total_loops,
        min_disk_size_bytes=args.min_disk_size_bytes,
        rng=rng,
    )
    if not rows:
        print("no powercycle fio rows generated")
        return 1

    write_csv(args.csv, rows)
    write_state(args.staged_state, next_state)

    print(f"loop={args.current_loop}/{args.total_loops}")
    for line in summary:
        print(line)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate random fio plans for reboot/dc powercycle tests.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan_parser = subparsers.add_parser("plan")
    plan_parser.add_argument("--state", required=True)
    plan_parser.add_argument("--staged-state", required=True)
    plan_parser.add_argument("--csv", required=True)
    plan_parser.add_argument("--current-loop", required=True, type=int)
    plan_parser.add_argument("--total-loops", required=True, type=int)
    plan_parser.add_argument("--min-disk-size-bytes", required=True, type=int)
    plan_parser.set_defaults(func=command_plan)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
