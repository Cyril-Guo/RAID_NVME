from test_items.random_io_plan import (
    DEFAULT_DURATION_SECONDS,
    DEFAULT_STRESS_RUNTIME,
    LBA_SIZE,
    MAX_SLICE_BYTES,
    MIN_SLICE_BYTES,
    MODEL_COUNT,
    PREP_IODEPTH,
    adaptive_slice_bytes,
    block_size_bytes,
    format_plan,
    generate_random_io_plan,
    layout_models_on_disk,
    parse_duration_seconds,
    peak_qd,
    plan_to_csv,
    plan_to_fio_job,
    regions_overlap_bytes,
)


def test_random_io_plan_has_sixteen_non_overlapping_512_aligned_models():
    plan = generate_random_io_plan(seed=42)

    assert plan["seed"] == 42
    assert plan["lba_size"] == LBA_SIZE == 512
    assert len(plan["models"]) == MODEL_COUNT

    signatures = []
    for model in plan["models"]:
        assert block_size_bytes(model["bs"]) % 512 == 0
        assert model["numjobs"] == 1
        assert model["verify"] == "crc32c"
        assert MIN_SLICE_BYTES <= model["slice_bytes"] <= MAX_SLICE_BYTES or model[
            "slice_bytes"
        ] == block_size_bytes(model["bs"])
        signatures.append(
            (model["name"], model["bs"], model["iodepth"], model["random_pct"], model["read_pct"])
        )
    assert len(set(signatures)) == MODEL_COUNT
    assert peak_qd(plan) == sum(model["iodepth"] for model in plan["models"])


def _rw_lines(job_text):
    return [line for line in job_text.splitlines() if line.startswith("rw=")]


def test_random_io_fio_job_fill_stress_verify_use_same_model_bs():
    plan = generate_random_io_plan(seed=42)
    disk_sizes = {"dp0-vd1": 64 * 1024**3, "dp0-vd2": 64 * 1024**3}
    fill_job = plan_to_fio_job(plan, disk_sizes, "FILL")
    stress_job = plan_to_fio_job(plan, disk_sizes, "STRESS")
    verify_job = plan_to_fio_job(plan, disk_sizes, "VERIFY")
    job_count = MODEL_COUNT * len(disk_sizes)

    assert fill_job.count("[m") == job_count
    assert _rw_lines(fill_job) == ["rw=write"] * job_count
    assert "do_verify=0" in fill_job
    assert "verify_only=1" not in fill_job
    assert "serialize_overlap=1" in fill_job
    assert f"iodepth={PREP_IODEPTH}" in fill_job

    assert stress_job.count("[m") == job_count
    assert "rw=write" in stress_job or "rw=randwrite" in stress_job or "rw=randrw" in stress_job or "rw=rw" in stress_job
    assert "do_verify=0" in stress_job
    assert "verify_only=1" not in stress_job
    assert any(model["name"] != "write" for model in plan["models"])
    assert _rw_lines(stress_job) != ["rw=write"] * job_count
    assert f"runtime={DEFAULT_STRESS_RUNTIME}" in stress_job
    assert "time_based=1" in stress_job
    custom_stress = plan_to_fio_job(plan, disk_sizes, "STRESS", stress_runtime=30)
    assert "runtime=30" in custom_stress
    assert "time_based=1" in custom_stress

    assert _rw_lines(verify_job) == ["rw=read"] * job_count
    assert "verify_only=1" in verify_job
    assert "time_based" not in verify_job
    assert f"iodepth={PREP_IODEPTH}" in verify_job

    for model in plan["models"]:
        assert fill_job.count(f"bs={model['bs']}") >= len(disk_sizes)
        assert stress_job.count(f"bs={model['bs']}") >= len(disk_sizes)
        assert verify_job.count(f"bs={model['bs']}") >= len(disk_sizes)

    assert "filename=/dev/dp0-vd1" in fill_job
    assert "verify=crc32c" in fill_job
    assert "verify=crc32c" in verify_job

    fill_offsets = [line for line in fill_job.splitlines() if line.startswith("offset=")]
    verify_offsets = [line for line in verify_job.splitlines() if line.startswith("offset=")]
    stress_offsets = [line for line in stress_job.splitlines() if line.startswith("offset=")]
    assert fill_offsets == verify_offsets == stress_offsets

    placements = layout_models_on_disk(plan, disk_sizes["dp0-vd1"], disk_key="dp0-vd1")
    assert len(placements) == MODEL_COUNT
    assert regions_overlap_bytes(placements) is False


def test_random_io_windows_scatter_across_whole_disk():
    plan = generate_random_io_plan(seed=42)
    disk_size = 64 * 1024**3
    placements = layout_models_on_disk(plan, disk_size, disk_key="dp0-vd1")
    assert regions_overlap_bytes(placements) is False

    payload = sum(item["size_bytes"] for item in placements)
    span = max(item["offset_bytes"] + item["size_bytes"] for item in placements) - min(
        item["offset_bytes"] for item in placements
    )
    assert span > payload * 2
    assert max(item["offset_bytes"] for item in placements) > disk_size // 4

    again = layout_models_on_disk(plan, disk_size, disk_key="dp0-vd1")
    assert [(p["offset_bytes"], p["size_bytes"], p["model"]["id"]) for p in again] == [
        (p["offset_bytes"], p["size_bytes"], p["model"]["id"]) for p in placements
    ]
    other = layout_models_on_disk(generate_random_io_plan(seed=99), disk_size, disk_key="dp0-vd1")
    assert [p["offset_bytes"] for p in other] != [p["offset_bytes"] for p in placements]


def test_format_plan_and_csv_include_real_byte_offsets():
    plan = generate_random_io_plan(seed=42)
    disk_sizes = {"dp0-vd1": 64 * 1024**3}
    table = format_plan(plan, disk_sizes=disk_sizes)
    csv_text = plan_to_csv(plan, disk_sizes=disk_sizes)
    placements = layout_models_on_disk(plan, disk_sizes["dp0-vd1"], disk_key="dp0-vd1")

    assert "multi-round coverage accumulates" in table
    assert "dp0-vd1" in table
    for place in placements:
        assert str(place["offset_bytes"]) in table
        assert str(place["offset_bytes"]) in csv_text
        assert str(place["size_bytes"]) in csv_text
    assert csv_text.startswith("Disk,Model_ID,")
    assert csv_text.count("FILL") == MODEL_COUNT
    assert csv_text.count("STRESS") == MODEL_COUNT
    assert csv_text.count("VERIFY") == MODEL_COUNT


def test_parse_duration_seconds(monkeypatch):
    monkeypatch.delenv("RANDOM_IO_DURATION", raising=False)
    assert parse_duration_seconds("") == DEFAULT_DURATION_SECONDS
    assert parse_duration_seconds("12h") == 12 * 3600
    assert parse_duration_seconds("90m") == 90 * 60
    assert parse_duration_seconds("30s") == 30
    assert parse_duration_seconds("120") == 120
    monkeypatch.setenv("RANDOM_IO_DURATION", "2h")
    assert parse_duration_seconds() == 2 * 3600


def test_adaptive_slice_bytes_clamps_small_and_large_bs():
    assert adaptive_slice_bytes("512") >= MIN_SLICE_BYTES
    assert adaptive_slice_bytes("16m") <= MAX_SLICE_BYTES
    assert adaptive_slice_bytes("4k") % block_size_bytes("4k") == 0


def test_random_io_seed_changes_the_model_set():
    first = generate_random_io_plan(seed=1)
    second = generate_random_io_plan(seed=2)
    assert [model["bs"] for model in first["models"]] != [model["bs"] for model in second["models"]] or [
        model["iodepth"] for model in first["models"]
    ] != [model["iodepth"] for model in second["models"]]
