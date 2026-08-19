from test_items.random_io_plan import (
    LBA_SIZE,
    MODEL_COUNT,
    block_size_bytes,
    format_plan,
    generate_random_io_plan,
    peak_qd,
    plan_to_csv,
    plan_to_fio_job,
    regions_overlap,
)


def test_random_io_plan_has_sixteen_non_overlapping_512_aligned_models():
    plan = generate_random_io_plan(seed=42)

    assert plan["seed"] == 42
    assert plan["lba_size"] == LBA_SIZE == 512
    assert len(plan["models"]) == MODEL_COUNT
    assert regions_overlap(plan["models"]) is False

    signatures = []
    offsets = []
    for model in plan["models"]:
        assert block_size_bytes(model["bs"]) % 512 == 0
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


def _rw_lines(job_text):
    return [line for line in job_text.splitlines() if line.startswith("rw=")]


def test_random_io_fio_job_fill_stress_verify_cover_whole_slices():
    plan = generate_random_io_plan(seed=42)
    disk_sizes = {"dp0-vd1": 512 * 1_000_000, "dp0-vd2": 512 * 1_000_000}
    fill_job = plan_to_fio_job(plan, disk_sizes, "FILL")
    stress_job = plan_to_fio_job(plan, disk_sizes, "STRESS")
    verify_job = plan_to_fio_job(plan, disk_sizes, "VERIFY")
    job_count = MODEL_COUNT * len(disk_sizes)

    assert fill_job.count("[m") == job_count
    assert _rw_lines(fill_job) == ["rw=write"] * job_count
    assert "do_verify=0" in fill_job
    assert "verify_only=1" not in fill_job

    assert stress_job.count("[m") == job_count
    assert "rw=write" in stress_job or "rw=randwrite" in stress_job or "rw=randrw" in stress_job or "rw=rw" in stress_job
    assert "do_verify=0" in stress_job
    assert "verify_only=1" not in stress_job
    assert any(model["name"] != "write" for model in plan["models"])
    assert _rw_lines(stress_job) != ["rw=write"] * job_count

    assert _rw_lines(verify_job) == ["rw=read"] * job_count
    assert "verify_only=1" in verify_job
    # First slice_id is 0 => offset bytes are 0.
    assert "offset=0B" in fill_job
    # size in bytes equals slice_lba * LBA_SIZE.
    total_lba = disk_sizes["dp0-vd1"] // LBA_SIZE
    slice_lba = int(total_lba * 6 / 100)
    expected_size_bytes = slice_lba * LBA_SIZE
    assert f"size={expected_size_bytes}B" in fill_job
    assert "filename=/dev/dp0-vd1" in fill_job
    assert fill_job.count("iodepth=") >= MODEL_COUNT
    assert "verify=crc32c" in fill_job
    assert "verify=crc32c" in verify_job


def test_random_io_plan_table_and_csv_are_readable():
    plan = generate_random_io_plan(seed=7)
    table = format_plan(plan)
    csv_text = plan_to_csv(plan)

    assert "Random IO FIO Plan" in table
    assert "FILL, then STRESS, then VERIFY" in table
    assert "Per-disk peak QD" in table
    assert "unwritten holes" in table
    assert table.count("\n") >= MODEL_COUNT
    assert csv_text.startswith("Block_Size,")
    assert csv_text.count("FILL") == MODEL_COUNT
    assert csv_text.count("STRESS") == MODEL_COUNT
    assert csv_text.count("VERIFY") == MODEL_COUNT
    assert csv_text.strip().endswith("End,,,,,,,,,")


def test_random_io_seed_changes_the_model_set(monkeypatch):
    monkeypatch.delenv("RANDOM_IO_SEED", raising=False)
    first = generate_random_io_plan(seed=1)
    second = generate_random_io_plan(seed=2)
    assert [model["bs"] for model in first["models"]] != [model["bs"] for model in second["models"]] or [
        model["iodepth"] for model in first["models"]
    ] != [model["iodepth"] for model in second["models"]]
