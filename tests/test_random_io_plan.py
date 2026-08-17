from test_items.random_io_plan import (
    LBA_SIZE,
    MODEL_COUNT,
    block_size_bytes,
    format_plan,
    generate_random_io_plan,
    plan_to_csv,
    regions_overlap,
)


def test_random_io_plan_has_sixteen_non_overlapping_4k_models():
    plan = generate_random_io_plan(seed=42)

    assert plan["seed"] == 42
    assert plan["lba_size"] == LBA_SIZE == 4096
    assert len(plan["models"]) == MODEL_COUNT
    assert regions_overlap(plan["models"]) is False

    signatures = []
    offsets = []
    for model in plan["models"]:
        assert block_size_bytes(model["bs"]) % 4096 == 0
        assert model["numjobs"] == 1
        assert model["verify"] == "crc32c"
        assert model["size_pct"] == 6
        signatures.append(
            (model["name"], model["bs"], model["iodepth"], model["random_pct"], model["read_pct"])
        )
        offsets.append(model["offset_pct"])
    assert len(set(signatures)) == MODEL_COUNT
    assert len(set(offsets)) == MODEL_COUNT
    assert max(offset + 6 for offset in offsets) <= 96


def test_random_io_plan_table_and_csv_are_readable():
    plan = generate_random_io_plan(seed=7)
    table = format_plan(plan)
    csv_text = plan_to_csv(plan)

    assert "Random IO FIO Plan" in table
    assert "WRITE then VERIFY" in table
    assert table.count("\n") >= MODEL_COUNT
    assert csv_text.startswith("Block_Size,")
    assert csv_text.count("WRITE") == MODEL_COUNT
    assert csv_text.count("VERIFY") == MODEL_COUNT
    assert csv_text.strip().endswith("End,,,,,,,,,")


def test_random_io_seed_changes_the_model_set(monkeypatch):
    monkeypatch.delenv("RANDOM_IO_SEED", raising=False)
    first = generate_random_io_plan(seed=1)
    second = generate_random_io_plan(seed=2)
    assert [model["bs"] for model in first["models"]] != [model["bs"] for model in second["models"]] or [
        model["iodepth"] for model in first["models"]
    ] != [model["iodepth"] for model in second["models"]]
