"""
Smoke 测试 —— 随机 IO 压力 + 数据一致性。

只暴露 RANDOM_IO_DURATION（总墙钟时长，到点停）。
每轮在整盘随机抽 16 个小窗口：FILL → STRESS → VERIFY（同 bs + crc32c）。
单轮不扫满盘，多轮统计累积覆盖。
"""
import os
import time

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
    parse_duration_seconds,
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

    duration_seconds = parse_duration_seconds()
    stress_runtime = DEFAULT_STRESS_RUNTIME
    deadline = time.monotonic() + duration_seconds

    jobs = {
        phase: os.path.join(stress_dir, f"random_io_{phase.lower()}.fio")
        for phase in PHASES
    }

    maybe_start_monitor()

    allure.dynamic.title("FIO 测试: random_io")
    round_idx = 0
    while time.monotonic() < deadline:
        round_idx += 1
        plan = generate_random_io_plan()
        table = format_plan(plan, disk_sizes=disk_sizes)
        write_plan_csv(plan, csv_path, disk_sizes=disk_sizes)

        write_fio_job(plan, disk_sizes, jobs["FILL"], "FILL")
        write_fio_job(plan, disk_sizes, jobs["STRESS"], "STRESS", stress_runtime=stress_runtime)
        write_fio_job(plan, disk_sizes, jobs["VERIFY"], "VERIFY")

        remaining = max(0, int(deadline - time.monotonic()))
        header = (
            f"{table}\n"
            f"[RANDOM_IO round {round_idx}] disks={','.join(disks)} count={len(disks)} "
            f"parallel_models=16 peak_stress_qd_per_disk={peak_qd(plan)} "
            f"duration={duration_seconds}s remaining≈{remaining}s "
            f"stress={stress_runtime}s\n"
        )
        print(header)
        allure.dynamic.description(
            f"Round {round_idx}: 16 随机窗口 FILL→STRESS({stress_runtime}s)→VERIFY，"
            f"同 bs+crc32c，seed={plan['seed']}，总时长={duration_seconds}s，"
            f"peak_stress_qd_per_disk={peak_qd(plan)}。"
        )
        attach_named_text(header, f"随机 IO 布局 (round {round_idx})")

        output = header
        for phase in PHASES:
            attach = phase == "VERIFY"
            output = run_and_check_argv(
                ["fio", os.path.basename(jobs[phase])],
                cwd=stress_dir,
                extra_output=output
                + f"[RANDOM_IO round {round_idx}] PHASE={phase} all 16 models together\n",
                attach=attach,
            )

    if round_idx == 0:
        pytest.fail(f"RANDOM_IO_DURATION 过短，未能跑完至少一轮: {duration_seconds}s")
    print(f"[RANDOM_IO] finished rounds={round_idx} duration={duration_seconds}s")
