"""Filesystem FIO stress. FIO_CONFIG points to CSV edited manually."""
import os

import allure
import pytest

from test_items.fio_run import build_fio_args, maybe_start_monitor, run_and_check_fio


def _item_name(default: str = "test_ci_02_filesystem") -> str:
    return (os.environ.get("RAID_NVME_ITEM") or default).strip() or default


def test_filesystem_stress():
    item = _item_name()
    runtime_text = os.environ.get("FIO_RUNTIME", "").strip()
    if (
        not runtime_text.isdigit()
        or int(runtime_text) < 180
        or int(runtime_text) % 180 != 0
    ):
        pytest.fail(
            f"FIO_RUNTIME must be >=180 and divisible by 180, got: {runtime_text}"
        )

    maybe_start_monitor()
    fio_args = build_fio_args("filesystemstress", item)
    allure.dynamic.title(f"FIO test: {item} random mixed IO")
    allure.dynamic.description(
        "4 partitions per disk, 16 fio models, iodepth=16; "
        "180s per round then change RW mix and align weights; "
        f"{int(runtime_text) // 180} rounds, total {runtime_text}s; "
        f"FIO_CONFIG={os.environ.get('FIO_CONFIG', '')}."
    )
    run_and_check_fio(fio_args)
