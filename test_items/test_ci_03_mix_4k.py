"""Mixed IO FIO stress (4k)."""
import os

import allure

from test_items.fio_run import build_fio_args, maybe_start_monitor, run_and_check_fio


def _item_name(default: str = "test_ci_03_mix_4k") -> str:
    return (os.environ.get("RAID_NVME_ITEM") or default).strip() or default


def test_mix_stress():
    item = _item_name()
    # Prefer explicit param; fall back to suffix.
    if not os.environ.get("IO_BS_ALIGN", "").strip():
        os.environ["IO_BS_ALIGN"] = "4k"
    maybe_start_monitor()
    fio_args = build_fio_args("lawdiskstress", item, extra=["--mix_io", "yes"])
    fail_on_any = os.environ.get("MIX_FAIL_ON_ANY", "no").strip().lower()
    allure.dynamic.title(f"FIO 测试: {item} (混合 IO)")
    allure.dynamic.description(
        f"混合读写；4 路 MixIO 由 random_choice_{os.environ.get('IO_BS_ALIGN', '4k')}.py 生成。"
        f" MIX_FAIL_ON_ANY={fail_on_any or 'no'}。"
    )
    print(
        f"[MIX] item={item} IO_BS_ALIGN={os.environ.get('IO_BS_ALIGN')} "
        f"MIX_FAIL_ON_ANY={fail_on_any or 'no'}"
    )
    run_and_check_fio(fio_args)
