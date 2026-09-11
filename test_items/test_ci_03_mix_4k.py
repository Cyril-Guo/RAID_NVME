"""Mixed IO FIO stress (4k)."""
import os

import allure

from test_items.fio_run import build_fio_args, run_and_check_fio


def _item_name(default: str = "test_ci_03_mix_4k") -> str:
    return (os.environ.get("RAID_NVME_ITEM") or default).strip() or default


def test_mix_4k_stress():
    item = _item_name()
    # Align is fixed by this case; not a test_items.txt parameter.
    os.environ["IO_BS_ALIGN"] = "4k"
    fio_args = build_fio_args("mixstress", item)
    fail_on_any = os.environ.get("MIX_FAIL_ON_ANY", "yes").strip().lower()
    allure.dynamic.title(f"FIO 测试: {item}（混合 IO / 4k）")
    allure.dynamic.description(
        f"混合读写；4 路 MixIO 由 random_choice_4k.py 生成"
        f"（1000 组 × 30s，块大小 4k 对齐）。"
        f" MIX_FAIL_ON_ANY={fail_on_any or 'yes'}。"
    )
    print(
        f"[MIX] item={item} mode=mixstress IO_BS_ALIGN=4k "
        f"MIX_FAIL_ON_ANY={fail_on_any or 'yes'}"
    )
    run_and_check_fio(fio_args)
