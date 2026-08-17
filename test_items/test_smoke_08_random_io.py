"""
Smoke 测试 —— 随机 IO 压力。

每次生成 16 个互不重叠的 FIO 模型，16 路并行 WRITE，再 16 路并行 crc32c VERIFY。
"""
import os

import allure
import pytest

from test_items.case_paths import io_stress_dir
from test_items.fio_allure import attach_named_text
from test_items.fio_run import maybe_start_monitor, run_and_check_argv
from test_items.random_io_plan import (
    format_plan,
    generate_random_io_plan,
    list_test_disks,
    peak_qd,
    write_fio_job,
    write_plan_csv,
)


def test_random_io():
    plan = generate_random_io_plan()
    table = format_plan(plan)
    stress_dir = io_stress_dir()
    csv_name = os.environ.get("FIO_CONFIG", "").strip() or "Input_Config_random_io.csv"
    csv_path = os.path.join(stress_dir, os.path.basename(csv_name.replace("\\", "/")))
    write_plan_csv(plan, csv_path)

    disks = list_test_disks()
    if not disks:
        pytest.fail("random_io 未找到测试盘。请设置 FIO_DISKS，或确保存在 dp*-vd* 虚拟盘。")

    write_job = os.path.join(stress_dir, "random_io_write.fio")
    verify_job = os.path.join(stress_dir, "random_io_verify.fio")
    write_fio_job(plan, disks, write_job, "WRITE")
    write_fio_job(plan, disks, verify_job, "VERIFY")

    header = (
        f"{table}\n"
        f"[RANDOM_IO] disks={','.join(disks)} count={len(disks)} "
        f"parallel_models=16 peak_qd_per_disk={peak_qd(plan)}\n"
    )
    print(header)
    allure.dynamic.title("FIO 测试: random_io")
    allure.dynamic.description(
        f"16 个随机 FIO 模型并行，LBA=4096，slice=6%，verify=crc32c，"
        f"seed={plan['seed']}，peak_qd_per_disk={peak_qd(plan)}。"
    )
    attach_named_text(header, "随机 IO 模型表")

    maybe_start_monitor()
    write_out = run_and_check_argv(
        ["fio", os.path.basename(write_job)],
        cwd=stress_dir,
        extra_output=header + "[RANDOM_IO] PHASE=WRITE all 16 models together\n",
        attach=False,
    )
    run_and_check_argv(
        ["fio", os.path.basename(verify_job)],
        cwd=stress_dir,
        extra_output=write_out + "\n[RANDOM_IO] PHASE=VERIFY all 16 models together\n",
    )
