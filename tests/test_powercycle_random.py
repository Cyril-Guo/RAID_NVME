import ast
import random
from dataclasses import asdict
from pathlib import Path

from IO_Stress.powercycle_random import (
    ALIGNMENT_BYTES,
    DEFAULT_STRESS_RUNTIME,
    FILL_VERIFY_IODEPTH,
    PowercycleModel,
    WINDOW_BYTES,
    WINDOW_COUNT,
    build_plan,
    generate_window_specs,
    layout_windows,
    model_to_row,
)


def test_generate_window_specs_scatter_across_disk():
    disk = 8 * 1024 * 1024 * 1024
    windows = generate_window_specs(disk, plan_seed=42, rng=random.Random(42))

    assert 1 <= len(windows) <= WINDOW_COUNT
    for model in windows:
        assert model.block_size % ALIGNMENT_BYTES == 0
        assert model.offset % ALIGNMENT_BYTES == 0
        assert model.size >= model.block_size
        assert model.offset + model.size <= disk

    offsets = [model.offset for model in windows]
    assert len(offsets) == len(set(offsets))
    for left, right in zip(sorted(offsets), sorted(offsets)[1:]):
        left_model = next(m for m in windows if m.offset == left)
        assert left + left_model.size <= right


def test_model_to_row_phase_mapping():
    model = generate_window_specs(8 * 1024**3, 7, rng=random.Random(7))[0]

    fill = model_to_row(model, "FILL")
    assert fill[1] == "0" and fill[2] == "0" and fill[3] == str(FILL_VERIFY_IODEPTH)
    assert fill[8] == "FILL"

    stress = model_to_row(model, "STRESS")
    assert stress[1] == "100" and stress[2] == "100"  # read-only on FILL windows
    assert stress[4] == str(DEFAULT_STRESS_RUNTIME)
    assert stress[8] == "STRESS"

    write_stress = model_to_row(model, "STRESS_WRITE")
    assert write_stress[8] == "STRESS_WRITE"
    assert write_stress[4] == str(DEFAULT_STRESS_RUNTIME)

    verify = model_to_row(model, "VERIFY")
    assert verify[1] == "0" and verify[2] == "100"
    assert verify[8] == "VERIFY"


def test_build_plan_verify_fill_stress_sequence():
    disk = 8 * 1024**3
    windows = generate_window_specs(disk, 99, rng=random.Random(99))
    state = {"pending_verify": True, "plan_seed": 99, "windows": [asdict(w) for w in windows]}

    rows, next_state, summary = build_plan(
        state=state,
        current_loop=1,
        total_loops=3,
        min_disk_size_bytes=disk,
        rng=random.Random(100),
    )

    count = len(windows)
    assert [row[8] for row in rows[:count]] == ["VERIFY"] * count
    assert [row[8] for row in rows[count : count * 2]] == ["FILL"] * count
    assert [row[8] for row in rows[count * 2 : count * 3]] == ["STRESS"] * count
    assert all(row[8] in {"STRESS_WRITE", "FILL", "STRESS", "VERIFY"} for row in rows)
    assert next_state["pending_verify"] is True
    assert len(next_state["windows"]) == count
    assert "verify previous windows" in summary[0]
    assert "fill+ro-stress" in summary[1] or "profile=" in summary[1]


def test_build_plan_final_loop_only_verifies():
    disk = 8 * 1024**3
    windows = generate_window_specs(disk, 11, rng=random.Random(11))
    state = {"pending_verify": True, "windows": [asdict(w) for w in windows]}

    rows, next_state, _ = build_plan(
        state=state,
        current_loop=3,
        total_loops=3,
        min_disk_size_bytes=disk,
    )

    assert len(rows) == len(windows)
    assert all(row[8] == "VERIFY" for row in rows)
    assert next_state["pending_verify"] is False
    assert next_state["windows"] is None


def test_build_plan_first_loop_skips_verify():
    rows, next_state, summary = build_plan(
        state={},
        current_loop=1,
        total_loops=3,
        min_disk_size_bytes=8 * 1024**3,
        rng=random.Random(1),
    )

    modes = [row[8] for row in rows]
    assert "VERIFY" not in modes
    assert modes.count("FILL") >= 1
    assert modes.count("STRESS") == modes.count("FILL")
    assert all(m in {"FILL", "STRESS", "STRESS_WRITE"} for m in modes)
    assert next_state["pending_verify"] is True
    assert "profile=" in summary[0] or "fill+ro-stress" in summary[0]


def test_legacy_single_model_state_still_verifies():
    state = {
        "pending_verify": True,
        "model": {
            "block_size": 4096,
            "queue_depth": 8,
            "offset": 0,
            "size": WINDOW_BYTES,
            "verify_type": "crc32c",
            "random_percentage": 0,
            "read_percentage": 0,
            "num_jobs": 1,
        },
    }

    rows, _, _ = build_plan(
        state=state,
        current_loop=2,
        total_loops=2,
        min_disk_size_bytes=8 * 1024**3,
    )

    assert len(rows) == 1
    assert rows[0][8] == "VERIFY"


def test_powercycle_random_uses_python39_compatible_annotations():
    source = Path("IO_Stress/powercycle_random.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    forbidden = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr)
    ]
    assert forbidden == []


def test_layout_windows_rejects_fragmented_disk():
    models = [
        PowercycleModel(
            block_size=4096,
            queue_depth=8,
            offset=0,
            size=WINDOW_BYTES,
        )
        for _ in range(3)
    ]
    try:
        layout_windows(models, WINDOW_BYTES * 2, plan_seed=1)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "too small" in str(exc) or "fragmented" in str(exc)


def test_write_state_is_atomic_and_readable(tmp_path):
    from IO_Stress import powercycle_random as pr

    path = tmp_path / "powercycle_state.json"
    payload = {"pending_verify": True, "windows": [{"offset": 0}]}
    pr.write_state(str(path), payload)
    assert path.is_file()
    assert not list(tmp_path.glob("*.tmp.*"))
    loaded = pr.load_state(str(path))
    assert loaded["pending_verify"] is True
    assert loaded["windows"][0]["offset"] == 0


def test_build_plan_stages_io_committed_false():
    from IO_Stress.powercycle_random import build_plan
    import random

    rows, next_state, _summary = build_plan(
        state={},
        current_loop=0,
        total_loops=2,
        min_disk_size_bytes=10 * 1024 ** 3,
        rng=random.Random(1),
    )
    assert rows
    assert next_state.get("io_committed") is False
    assert next_state.get("pending_verify") is True



def test_layout_windows_covers_disk_stripes():
    disk = 16 * 1024 * 1024 * 1024
    windows = generate_window_specs(disk, plan_seed=123, rng=random.Random(123))
    assert len(windows) >= 8
    offsets = sorted(m.offset for m in windows)
    # First window in early band, last window in late band.
    assert offsets[0] < disk // 4
    assert offsets[-1] >= (disk * 3) // 4


def test_stress_is_readonly_on_verify_windows():
    model = generate_window_specs(8 * 1024**3, 3, rng=random.Random(3))[0]
    stress = model_to_row(model, "STRESS")
    assert stress[2] == "100"


def test_resolve_profile_release_stronger_than_smoke(monkeypatch):
    from IO_Stress.powercycle_random import resolve_profile

    monkeypatch.delenv("POWERCYCLE_WINDOW_COUNT", raising=False)
    monkeypatch.delenv("POWERCYCLE_WINDOW_BYTES", raising=False)
    monkeypatch.setenv("POWERCYCLE_PROFILE", "smoke")
    smoke = resolve_profile()
    monkeypatch.setenv("POWERCYCLE_PROFILE", "release")
    release = resolve_profile()
    assert release["window_count"] >= smoke["window_count"]
    assert release["window_bytes"] >= smoke["window_bytes"]
    assert release["stress_runtime"] >= smoke["stress_runtime"]
