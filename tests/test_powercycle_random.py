import json
from pathlib import Path

from IO_Stress.powercycle_random import (
    ALIGNMENT_BYTES,
    AVOID_ALIGNMENT_BYTES,
    MAX_BLOCK_BYTES,
    MIN_BLOCK_BYTES,
    MIN_REGION_BYTES,
    build_plan,
    generate_model,
)


def test_generate_model_stays_in_required_range():
    model = generate_model(8 * 1024 * 1024 * 1024)

    assert MIN_BLOCK_BYTES <= model.block_size <= MAX_BLOCK_BYTES
    assert model.block_size % ALIGNMENT_BYTES == 0
    assert model.block_size % AVOID_ALIGNMENT_BYTES != 0
    assert model.offset % ALIGNMENT_BYTES == 0
    assert model.size >= MIN_REGION_BYTES
    assert model.offset + model.size <= 8 * 1024 * 1024 * 1024


def test_build_plan_verifies_previous_then_writes_next():
    state = {
        "pending_verify": True,
        "model": {
            "block_size": 1536,
            "queue_depth": 8,
            "offset": 5120,
            "size": 64 * 1024 * 1024,
            "verify_type": "crc32c",
            "random_percentage": 0,
            "read_percentage": 0,
            "num_jobs": 1,
        },
    }

    rows, next_state, summary = build_plan(
        state=state,
        current_loop=1,
        total_loops=3,
        min_disk_size_bytes=8 * 1024 * 1024 * 1024,
    )

    assert len(rows) == 2
    assert rows[0][8] == "VERIFY"
    assert rows[1][8] == "WRITE"
    assert next_state["pending_verify"] is True
    assert "verify previous model" in summary[0]
    assert "write next model" in summary[1]


def test_build_plan_final_loop_only_verifies():
    state = {
        "pending_verify": True,
        "model": {
            "block_size": 1536,
            "queue_depth": 8,
            "offset": 5120,
            "size": 64 * 1024 * 1024,
            "verify_type": "crc32c",
            "random_percentage": 0,
            "read_percentage": 0,
            "num_jobs": 1,
        },
    }

    rows, next_state, _ = build_plan(
        state=state,
        current_loop=3,
        total_loops=3,
        min_disk_size_bytes=8 * 1024 * 1024 * 1024,
    )

    assert len(rows) == 1
    assert rows[0][8] == "VERIFY"
    assert next_state["pending_verify"] is False
    assert next_state["model"] is None
