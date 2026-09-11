"""Mixed IO FIO stress (512)."""
import os

import allure

from test_items.fio_run import build_fio_args, run_and_check_fio


def _item_name(default: str = "test_ci_04_mix_512") -> str:
    return (os.environ.get("RAID_NVME_ITEM") or default).strip() or default


def test_mix_512_stress():
    item = _item_name()
    # Direct model script — fio.sh runs this file (no IO_BS_ALIGN dispatcher).
    os.environ["MIX_RANDOM_CHOICE"] = "random_choice_512.py"
    fio_args = build_fio_args("mixstress", item)
    fail_on_any = os.environ.get("MIX_FAIL_ON_ANY", "yes").strip().lower()
    allure.dynamic.title(f"FIO 测试: {item}（混合 IO / 512）")
    allure.dynamic.description(
        f"混合读写；4 路 MixIO 由 random_choice_512.py 直接生成"
        f"（1000 组 × 30s，块大小 512 对齐）。"
        f" MIX_FAIL_ON_ANY={fail_on_any or 'yes'}。"
    )
    print(
        f"[MIX] item={item} mode=mixstress MIX_RANDOM_CHOICE=random_choice_512.py "
        f"MIX_FAIL_ON_ANY={fail_on_any or 'yes'}"
    )
    run_and_check_fio(fio_args)
