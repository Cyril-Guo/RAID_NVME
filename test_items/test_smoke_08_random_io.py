"""
Smoke 测试 —— 随机 IO 压力。

每次生成 16 个互不重叠的 FIO 模型（4k 倍数块、变化 QD/读写模式/offset），
先 WRITE 再 crc32c VERIFY，用于把 FIO 压力跑彻底并暴露数据一致性问题。
"""
import os

import allure

from test_items.case_paths import io_stress_dir
from test_items.fio_allure import attach_named_text
from test_items.fio_run import build_fio_args, maybe_start_monitor, run_and_check_fio
from test_items.random_io_plan import generate_random_io_plan, format_plan, write_plan_csv


def test_random_io():
    plan = generate_random_io_plan()
    table = format_plan(plan)
    csv_name = os.environ.get("FIO_CONFIG", "").strip() or "Input_Config_random_io.csv"
    csv_path = os.path.join(io_stress_dir(), os.path.basename(csv_name.replace("\\", "/")))
    write_plan_csv(plan, csv_path)

    print(table)
    print(f"[RANDOM_IO] wrote {csv_path}")
    allure.dynamic.title("FIO 测试: random_io")
    allure.dynamic.description(
        f"16 个随机 FIO 模型，LBA=4096，slice=6%，verify=crc32c，seed={plan['seed']}。"
    )
    attach_named_text(table, "随机 IO 模型表")

    maybe_start_monitor()
    run_and_check_fio(
        build_fio_args("lawdiskstress", "random_io"),
        extra_output=table + "\n",
    )
