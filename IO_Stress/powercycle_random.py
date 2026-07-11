import argparse
import csv
import json
import math
import os
import random
from dataclasses import asdict, dataclass


MIN_BLOCK_BYTES = 512
MAX_BLOCK_BYTES = 16 * 1024 * 1024
ALIGNMENT_BYTES = 512
AVOID_ALIGNMENT_BYTES = 4096
MIN_REGION_BYTES = 64 * 1024 * 1024
MAX_REGION_BYTES = 1024 * 1024 * 1024
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


@dataclass
class PowercycleModel:
    block_size: int
    queue_depth: int
    offset: int
    size: int
    verify_type: str = "crc32c"
    random_percentage: int = 0
    read_percentage: int = 0
    num_jobs: int = 1


def _aligned_random(rng: random.Random, minimum: int, maximum: int, *, avoid_alignment: int | None = None) -> int:
    if maximum < minimum:
        raise ValueError(f"invalid range: {minimum}..{maximum}")
    start = math.ceil(minimum / ALIGNMENT_BYTES) * ALIGNMENT_BYTES
    stop = math.floor(maximum / ALIGNMENT_BYTES) * ALIGNMENT_BYTES
    if stop < start:
        raise ValueError(f"empty aligned range: {minimum}..{maximum}")

    attempts = 64
    for _ in range(attempts):
        steps = ((stop - start) // ALIGNMENT_BYTES) + 1
        value = start + rng.randrange(steps) * ALIGNMENT_BYTES
        if avoid_alignment and value >= avoid_alignment and value % avoid_alignment == 0:
            continue
        return value

    return start


def _bounded_region_limit(disk_size: int) -> int:
    return min(MAX_REGION_BYTES, max(MIN_REGION_BYTES, disk_size // 8))


def generate_model(min_disk_size_bytes: int, rng: random.Random | None = None) -> PowercycleModel:
    rng = rng or random.Random()
    if min_disk_size_bytes < MIN_REGION_BYTES * 2:
        raise ValueError(f"disk too small for powercycle model: {min_disk_size_bytes}")

    block_size = _aligned_random(
        rng,
        MIN_BLOCK_BYTES,
        min(MAX_BLOCK_BYTES, min_disk_size_bytes // 16),
        avoid_alignment=AVOID_ALIGNMENT_BYTES,
    )

    region_max = _bounded_region_limit(min_disk_size_bytes)
    region_min = max(8 * 1024 * 1024, min(MIN_REGION_BYTES, block_size * 128))
    region_max = min(region_max, max(region_min, min_disk_size_bytes // 4))
    size = _aligned_random(rng, region_min, region_max)

    remaining = min_disk_size_bytes - size
    if remaining < 0:
        raise ValueError("generated region exceeds disk size")

    offset = 0
    if remaining >= ALIGNMENT_BYTES:
        offset = _aligned_random(rng, 0, remaining, avoid_alignment=AVOID_ALIGNMENT_BYTES)

    queue_depth = rng.choice([1, 2, 4, 8, 16, 32])

    return PowercycleModel(
        block_size=block_size,
        queue_depth=queue_depth,
        offset=offset,
        size=size,
    )


def model_to_row(model: PowercycleModel, verify_mode: str) -> list[str]:
    return [
        str(model.block_size),
        str(model.random_percentage),
        str(model.read_percentage),
        str(model.queue_depth),
        "0",
        str(model.num_jobs),
        str(model.offset),
        str(model.size),
        verify_mode,
        model.verify_type,
    ]


def load_state(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def write_state(path: str, payload: dict) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)


def build_plan(state: dict, current_loop: int, total_loops: int, min_disk_size_bytes: int, rng: random.Random | None = None):
    rng = rng or random.Random()
    rows: list[list[str]] = []
    summary: list[str] = []

    pending_model = state.get("model") if state.get("pending_verify") else None
    if pending_model:
        model = PowercycleModel(**pending_model)
        rows.append(model_to_row(model, "VERIFY"))
        summary.append(
            f"verify previous model: bs={model.block_size} offset={model.offset} size={model.size} qd={model.queue_depth}"
        )

    next_state = {"pending_verify": False, "model": None}
    if current_loop < total_loops:
        new_model = generate_model(min_disk_size_bytes, rng=rng)
        rows.append(model_to_row(new_model, "WRITE"))
        next_state = {"pending_verify": True, "model": asdict(new_model)}
        summary.append(
            f"write next model: bs={new_model.block_size} offset={new_model.offset} size={new_model.size} qd={new_model.queue_depth}"
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
