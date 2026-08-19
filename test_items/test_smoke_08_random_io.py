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
    DEFAULT_STRESS_RUNTIME,
    PHASES,
    format_plan,
    generate_random_io_plan,
    list_test_disks,
    peak_qd,
    write_fio_job,
    write_plan_csv,
)


def test_random_io():
    stress_dir = io_stress_dir()
    csv_name = os.environ.get("FIO_CONFIG", "").strip() or "Input_Config_random_io.csv"
    csv_path = os.path.join(stress_dir, os.path.basename(csv_name.replace("\\", "/")))

    disk_sizes = list_test_disks()
    if not disk_sizes:
        pytest.fail("random_io 未找到测试盘。请设置 FIO_DISKS，或确保存在 dp*-vd* 虚拟盘。")
    disks = list(disk_sizes.keys())

    _raw_rt = os.environ.get("RANDOM_IO_STRESS_RUNTIME", "").strip()
    stress_runtime = int(_raw_rt) if _raw_rt else DEFAULT_STRESS_RUNTIME

    _raw_loops = os.environ.get("RANDOM_IO_LOOPS", "").strip()
    loops = int(_raw_loops) if _raw_loops else 1
    if loops <= 0:
        pytest.fail(f"RANDOM_IO_LOOPS 必须 > 0，但当前是: {loops}")

    base_seed_raw = os.environ.get("RANDOM_IO_SEED", "").strip()
    base_seed = int(base_seed_raw) if base_seed_raw else None

    jobs = {
        phase: os.path.join(stress_dir, f"random_io_{phase.lower()}.fio")
        for phase in PHASES
    }
    fill_job = jobs["FILL"]

    maybe_start_monitor()

    allure.dynamic.title("FIO 测试: random_io")
    for round_idx in range(loops):
        # 每一轮都要“重新随机生成 16 个模型”
        plan_seed = (base_seed + round_idx) if base_seed is not None else None
        plan = generate_random_io_plan(seed=plan_seed)
        table = format_plan(plan)
        write_plan_csv(plan, csv_path)

        # 每轮覆盖对应 fio job 文件
        write_fio_job(plan, disk_sizes, fill_job, "FILL")
        write_fio_job(plan, disk_sizes, jobs["STRESS"], "STRESS", stress_runtime=stress_runtime)
        write_fio_job(plan, disk_sizes, jobs["VERIFY"], "VERIFY")

        header = (
            f"{table}\n"
            f"[RANDOM_IO round {round_idx + 1}/{loops}] disks={','.join(disks)} count={len(disks)} "
            f"parallel_models=16 peak_qd_per_disk={peak_qd(plan)}\n"
        )
        print(header)
        allure.dynamic.description(
            f"Round {round_idx + 1}/{loops}: 16 个随机 FIO 模型：FILL → STRESS({stress_runtime}s) → VERIFY，"
            f"LBA={plan['lba_size']}，slice=6%，verify=crc32c，seed={plan['seed']}，"
            f"peak_qd_per_disk={peak_qd(plan)}。"
        )
        attach_named_text(header, f"随机 IO 模型表 (round {round_idx + 1})")

        output = header
        for phase in PHASES:
            attach = phase == "VERIFY"
            output = run_and_check_argv(
                ["fio", os.path.basename(jobs[phase])],
                cwd=stress_dir,
                extra_output=output
                + f"[RANDOM_IO round {round_idx + 1}/{loops}] PHASE={phase} all 16 models together\n",
                attach=attach,
            )
