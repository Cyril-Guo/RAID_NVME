"""Mixed IO FIO stress (512)."""
import os

import allure

from test_items.fio_run import build_fio_args, run_and_check_fio


def _item_name(default: str = "test_ci_04_mix_512") -> str:
    return (os.environ.get("RAID_NVME_ITEM") or default).strip() or default


def test_mix_stress():
    item = _item_name()
    # Align is fixed by this case; not a test_items.txt parameter.
    os.environ["IO_BS_ALIGN"] = "512"
    fio_args = build_fio_args("lawdiskstress", item, extra=["--mix_io", "yes"])
    fail_on_any = os.environ.get("MIX_FAIL_ON_ANY", "no").strip().lower()
    allure.dynamic.title(f"FIO 测试: {item} (混合 IO)")
    allure.dynamic.description(
        f"混合读写；4 路 MixIO 由 random_choice_512.py 生成（=拆分前统一 random_choice.py @2f19976 原样）。"
        f" MIX_FAIL_ON_ANY={fail_on_any or 'no'}。"
    )
    print(
        f"[MIX] item={item} IO_BS_ALIGN=512 "
        f"MIX_FAIL_ON_ANY={fail_on_any or 'no'}"
    )
    run_and_check_fio(fio_args)
