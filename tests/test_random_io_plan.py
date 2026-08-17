from test_items.random_io_plan import (
    LBA_SIZE,
    MODEL_COUNT,
    block_size_bytes,
    format_plan,
    generate_random_io_plan,
    peak_qd,
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
    assert peak_qd(plan) == sum(model["iodepth"] for model in plan["models"])


def test_random_io_fio_job_runs_all_models_in_one_file():
    from test_items.random_io_plan import plan_to_fio_job

    plan = generate_random_io_plan(seed=42)
    disks = ["dp0-vd1", "dp0-vd2"]
    write_job = plan_to_fio_job(plan, disks, "WRITE")
    verify_job = plan_to_fio_job(plan, disks, "VERIFY")
    assert write_job.count("[m") == MODEL_COUNT * len(disks)
    assert "do_verify=0" in write_job
    assert "verify_only=1" in verify_job
    assert "offset=0%" in write_job
    assert "size=6%" in write_job
    assert "filename=/dev/dp0-vd1" in write_job
    assert write_job.count("iodepth=") >= MODEL_COUNT



def test_random_io_plan_table_and_csv_are_readable():
    plan = generate_random_io_plan(seed=7)
    table = format_plan(plan)
    csv_text = plan_to_csv(plan)

    assert "Random IO FIO Plan" in table
    assert "PARALLEL WRITE, then PARALLEL VERIFY" in table
    assert "Per-disk peak QD" in table
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
