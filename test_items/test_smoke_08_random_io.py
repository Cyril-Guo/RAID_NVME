"""
Smoke 测试 —— 随机 IO 压力。

16 个互不重叠切片：先顺序 FILL 打满 crc32c 头，再按模型并行 STRESS，
最后顺序 VERIFY。校验失败表示盘上数据不一致，而不是未写入空洞。
"""
import os

import allure
import pytest

from test_items.case_paths import io_stress_dir
from test_items.fio_allure import attach_named_text
from test_items.fio_run import maybe_start_monitor, run_and_check_argv
from test_items.random_io_plan import (
    PHASES,
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

    jobs = {
        phase: os.path.join(stress_dir, f"random_io_{phase.lower()}.fio")
        for phase in PHASES
    }
    fill_job = jobs["FILL"]
    write_fio_job(plan, disks, fill_job, "FILL")
    write_fio_job(plan, disks, jobs["STRESS"], "STRESS")
    write_fio_job(plan, disks, jobs["VERIFY"], "VERIFY")

    header = (
        f"{table}\n"
        f"[RANDOM_IO] disks={','.join(disks)} count={len(disks)} "
        f"parallel_models=16 peak_qd_per_disk={peak_qd(plan)}\n"
    )
    print(header)
    allure.dynamic.title("FIO 测试: random_io")
    allure.dynamic.description(
        f"16 个随机 FIO 模型：FILL → STRESS → VERIFY，LBA=4096，slice=6%，"
        f"verify=crc32c，seed={plan['seed']}，peak_qd_per_disk={peak_qd(plan)}。"
    )
    attach_named_text(header, "随机 IO 模型表")

    maybe_start_monitor()
    output = header
    for phase in PHASES:
        attach = phase == "VERIFY"
        output = run_and_check_argv(
            ["fio", os.path.basename(jobs[phase])],
            cwd=stress_dir,
            extra_output=output + f"[RANDOM_IO] PHASE={phase} all 16 models together\n",
            attach=attach,
        )
