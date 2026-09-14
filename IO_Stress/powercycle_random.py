import argparse
import csv
import hashlib
import json
import os
import random
from dataclasses import asdict, dataclass
from typing import List, Optional

# Scattered windows per loop; FILL/STRESS before reboot, VERIFY after reboot.
WINDOW_COUNT = 32  # release default; profile/env may override via resolve_profile()
WINDOW_BYTES = 128 * 1024 * 1024
DEFAULT_STRESS_RUNTIME = 45
FILL_VERIFY_IODEPTH = 64
MIN_BLOCK_BYTES = 512
MAX_BLOCK_BYTES = 16 * 1024 * 1024
ALIGNMENT_BYTES = 512
VERIFY_TYPE = "crc32c"

# Profiles (overridable by env / test_items.txt):
#   smoke   - daily CI
#   release - stronger coverage for pre-release soak
_PROFILE_DEFAULTS = {
    "smoke": {
        "window_count": 16,
        "window_bytes": 128 * 1024 * 1024,
        "stress_runtime": 45,
        "write_stress_windows": 8,
        "verify_retries": 1,
    },
    "release": {
        "window_count": 32,
        "window_bytes": 512 * 1024 * 1024,
        "stress_runtime": 120,
        "write_stress_windows": 16,
        "verify_retries": 2,
    },
}


def resolve_profile(name: Optional[str] = None) -> dict:
    profile = (name or os.environ.get("POWERCYCLE_PROFILE") or "release").strip().lower()
    if profile not in _PROFILE_DEFAULTS:
        profile = "release"
    cfg = dict(_PROFILE_DEFAULTS[profile])
    cfg["name"] = profile

    def _env_int(key: str, dest: str) -> None:
        raw = os.environ.get(key, "").strip()
        if not raw:
            return
        try:
            cfg[dest] = max(1, int(raw))
        except ValueError:
            pass

    _env_int("POWERCYCLE_WINDOW_COUNT", "window_count")
    _env_int("POWERCYCLE_WINDOW_BYTES", "window_bytes")
    _env_int("POWERCYCLE_STRESS_RUNTIME", "stress_runtime")
    _env_int("POWERCYCLE_WRITE_STRESS_WINDOWS", "write_stress_windows")
    _env_int("POWERCYCLE_VERIFY_RETRIES", "verify_retries")
    return cfg


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


def _effective_window_count(disk_size_bytes: int, window_bytes: int, window_count: int) -> int:
    if disk_size_bytes < window_bytes:
        return 1
    by_size = max(1, disk_size_bytes // window_bytes)
    return min(window_count, by_size)


def _window_size_bytes(block_size: int, window_bytes: int) -> int:
    size = _align_down(window_bytes, block_size) or block_size
    return max(size, block_size)


def layout_windows(
    models: List[PowercycleModel],
    disk_size_bytes: int,
    plan_seed: int,
) -> List[PowercycleModel]:
    """Place one window in each equal LBA stripe so coverage spans head→tail.

    Within each stripe the offset is still randomized (deterministic from plan_seed).
    Falls back to free-space packing only if a stripe cannot hold its window.
    """
    if disk_size_bytes < ALIGNMENT_BYTES:
        raise ValueError(f"disk too small: {disk_size_bytes}")

    count = len(models)
    total_payload = sum(model.size for model in models)
    if total_payload > disk_size_bytes:
        raise ValueError(
            f"disk too small for {count} windows: need {total_payload}B, have {disk_size_bytes}B"
        )

    rng = random.Random(_layout_seed(plan_seed, disk_size_bytes))
    placed: List[PowercycleModel] = []
    occupied: List[tuple[int, int]] = []

    def overlaps(start: int, end: int) -> bool:
        for left, right in occupied:
            if start < right and end > left:
                return True
        return False

    for index, model in enumerate(models):
        bs = model.block_size
        size_bytes = model.size
        band_start = (disk_size_bytes * index) // count
        band_end = (disk_size_bytes * (index + 1)) // count
        if band_end - band_start < size_bytes:
            band_start = 0
            band_end = disk_size_bytes

        aligned_start = _align_up(band_start, bs)
        max_start = _align_down(band_end - size_bytes, bs)
        offset_bytes = None
        if max_start >= aligned_start:
            steps = ((max_start - aligned_start) // bs) + 1
            for _ in range(steps):
                candidate = aligned_start + rng.randrange(steps) * bs
                if not overlaps(candidate, candidate + size_bytes):
                    offset_bytes = candidate
                    break

        if offset_bytes is None:
            # Fallback: search whole disk for a free aligned slot.
            aligned_start = _align_up(0, bs)
            max_start = _align_down(disk_size_bytes - size_bytes, bs)
            if max_start < aligned_start:
                raise ValueError(
                    f"disk too fragmented for window bs={bs} size={size_bytes} on {disk_size_bytes}B disk"
                )
            steps = ((max_start - aligned_start) // bs) + 1
            for _ in range(min(steps, 4096)):
                candidate = aligned_start + rng.randrange(steps) * bs
                if not overlaps(candidate, candidate + size_bytes):
                    offset_bytes = candidate
                    break
            if offset_bytes is None:
                raise ValueError(
                    f"disk too fragmented for window bs={bs} size={size_bytes} on {disk_size_bytes}B disk"
                )

        occupied.append((offset_bytes, offset_bytes + size_bytes))
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
    *,
    window_count: Optional[int] = None,
    window_bytes: Optional[int] = None,
    occupied: Optional[List[tuple[int, int]]] = None,
) -> List[PowercycleModel]:
    rng = rng or random.Random(plan_seed)
    profile = resolve_profile()
    win_count = window_count if window_count is not None else profile["window_count"]
    win_bytes = window_bytes if window_bytes is not None else profile["window_bytes"]
    count = _effective_window_count(disk_size_bytes, win_bytes, win_count)
    rw_pool = list(RW_CHOICES)
    rng.shuffle(rw_pool)

    specs: List[PowercycleModel] = []
    for index in range(count):
        block_size = rng.choice(BLOCK_SIZES_BYTES)
        if block_size > MAX_BLOCK_BYTES:
            block_size = MAX_BLOCK_BYTES
        size_bytes = _window_size_bytes(block_size, win_bytes)
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

    placed = layout_windows(specs, disk_size_bytes, plan_seed)
    if not occupied:
        return placed

    # Re-place avoiding occupied ranges (for write-stress windows).
    return layout_windows_avoiding(placed, disk_size_bytes, plan_seed ^ 0xA5A5, occupied)



def layout_windows_avoiding(
    models: List[PowercycleModel],
    disk_size_bytes: int,
    plan_seed: int,
    occupied: List[tuple[int, int]],
) -> List[PowercycleModel]:
    """Place models into free space that does not overlap occupied FILL/VERIFY windows."""
    rng = random.Random(_layout_seed(plan_seed, disk_size_bytes))
    busy = list(occupied)
    placed: List[PowercycleModel] = []

    def overlaps(start: int, end: int) -> bool:
        for left, right in busy:
            if start < right and end > left:
                return True
        return False

    for model in models:
        bs = model.block_size
        size_bytes = model.size
        aligned_start = _align_up(0, bs)
        max_start = _align_down(disk_size_bytes - size_bytes, bs)
        if max_start < aligned_start:
            raise ValueError(f"disk too small for avoid-layout window size={size_bytes}")
        steps = ((max_start - aligned_start) // bs) + 1
        offset_bytes = None
        for _ in range(min(steps, 8192)):
            candidate = aligned_start + rng.randrange(steps) * bs
            if not overlaps(candidate, candidate + size_bytes):
                offset_bytes = candidate
                break
        if offset_bytes is None:
            raise ValueError("unable to place write-stress window outside FILL/VERIFY regions")
        busy.append((offset_bytes, offset_bytes + size_bytes))
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
        # Read-only stress on FILL/VERIFY windows so crc32c payload survives to next-loop VERIFY.
        random_pct = 100
        read_pct = 100
        run_time = str(stress_runtime)
    elif verify_mode == "STRESS_WRITE":
        # Writable stress in free LBA space (never part of pending_verify).
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
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    tmp_path = f"{path}.tmp.{os.getpid()}"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, path)
    # fsync directory entry so rename survives crash/power loss.
    try:
        dir_fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except OSError:
        pass


def build_plan(
    state: dict,
    current_loop: int,
    total_loops: int,
    min_disk_size_bytes: int,
    rng: Optional[random.Random] = None,
):
    rng = rng or random.Random()
    profile = resolve_profile()
    stress_runtime = profile["stress_runtime"]
    rows: list[list[str]] = []
    summary: list[str] = []

    pending = _pending_windows(state)
    if pending:
        for model_data in pending:
            model = PowercycleModel(**model_data)
            rows.append(model_to_row(model, "VERIFY", stress_runtime=stress_runtime))
        summary.append(
            "verify previous windows: "
            + ", ".join(
                f"bs={m.block_size} off={m.offset} sz={m.size} qd={m.queue_depth}"
                for m in (PowercycleModel(**item) for item in pending)
            )
        )

    next_state = {"pending_verify": False, "windows": None, "plan_seed": None, "io_committed": False}
    if current_loop < total_loops:
        plan_seed = rng.randint(1, 2**31 - 1)
        windows = generate_window_specs(
            min_disk_size_bytes,
            plan_seed,
            rng=rng,
            window_count=profile["window_count"],
            window_bytes=profile["window_bytes"],
        )
        for model in windows:
            rows.append(model_to_row(model, "FILL", stress_runtime=stress_runtime))
        # Read-only stress on FILL windows (must not destroy verify payload).
        for model in windows:
            rows.append(model_to_row(model, "STRESS", stress_runtime=stress_runtime))

        occupied = [(m.offset, m.offset + m.size) for m in windows]
        write_n = min(
            profile["write_stress_windows"],
            max(1, min_disk_size_bytes // max(profile["window_bytes"], 1) // 4),
        )
        write_windows: List[PowercycleModel] = []
        try:
            write_windows = generate_window_specs(
                min_disk_size_bytes,
                plan_seed ^ 0x5F5F,
                rng=rng,
                window_count=write_n,
                window_bytes=profile["window_bytes"],
                occupied=occupied,
            )
            for model in write_windows:
                rows.append(model_to_row(model, "STRESS_WRITE", stress_runtime=stress_runtime))
        except ValueError as exc:
            summary.append(f"write-stress skipped: {exc}")

        next_state = {
            "pending_verify": True,
            "plan_seed": plan_seed,
            "windows": [asdict(model) for model in windows],
            "io_committed": False,
            "profile": profile["name"],
        }
        summary.append(
            f"profile={profile['name']} fill+ro-stress {len(windows)} windows "
            f"+ write-stress {len(write_windows)} free windows "
            f"(seed={plan_seed}, stress={stress_runtime}s, window_bytes={profile['window_bytes']})"
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
