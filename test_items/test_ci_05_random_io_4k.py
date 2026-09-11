"""
Smoke 测试 —— 随机 IO 压力 + 数据一致性（4k 对齐）。

只暴露 RANDOM_IO_DURATION（总墙钟时长，默认 43200s=12h；可手写任意时长，如 Nh/Nm/Ns 或纯秒数）。
时长到点后：当前轮若已开始则跑完 FILL→STRESS→VERIFY 再结束，不新开下一轮。
每轮在整盘随机抽 16 个小窗口：FILL → STRESS → VERIFY（同 bs + crc32c）。
布局由 random_io_plan_4k 生成；无 Input_Config CSV。
"""
import os
import time

import allure
import pytest

from test_items.case_paths import io_stress_dir
from test_items.fio_allure import attach_named_text
from test_items.fio_run import run_and_check_argv
from test_items.random_io_plan_4k import (
    DEFAULT_STRESS_RUNTIME,
    PHASES,
    format_consistency_result,
    format_plan,
    generate_random_io_plan,
    list_test_disks,
    parse_duration_seconds,
    peak_qd,
    write_fio_job,
    write_plan_csv,
)


def test_random_io():
    item = (os.environ.get("RAID_NVME_ITEM") or "test_ci_05_random_io_4k").strip() or "test_ci_05_random_io_4k"

    stress_dir = io_stress_dir()
    disk_sizes = list_test_disks()
    if not disk_sizes:
        pytest.fail("random_io 未找到测试盘。请设置 FIO_DISKS，或确保存在 dp*-vd* 虚拟盘。")
    disks = list(disk_sizes.keys())

    duration_seconds = parse_duration_seconds()
    stress_runtime = DEFAULT_STRESS_RUNTIME
    started = time.monotonic()
    deadline = started + duration_seconds

    jobs = {
        phase: os.path.join(stress_dir, f"random_io_{phase.lower()}.fio")
        for phase in PHASES
    }

    allure.dynamic.title("FIO 测试: random_io_4k")
    round_idx = 0
    # Gate new rounds on wall-clock budget only. Once a round starts,
    # always finish FILL->STRESS->VERIFY even if deadline passes mid-round.
    while time.monotonic() < deadline:
        round_idx += 1
        plan = generate_random_io_plan()
        table = format_plan(plan, disk_sizes=disk_sizes)
        write_plan_csv(
            plan,
            os.path.join(stress_dir, f"random_io_layout_round{round_idx}.csv"),
            disk_sizes=disk_sizes,
        )

        write_fio_job(plan, disk_sizes, jobs["FILL"], "FILL")
        write_fio_job(
            plan, disk_sizes, jobs["STRESS"], "STRESS", stress_runtime=stress_runtime
        )
        write_fio_job(plan, disk_sizes, jobs["VERIFY"], "VERIFY")

        remaining = max(0, int(deadline - time.monotonic()))
        header = (
            f"{table}\n"
            f"[RANDOM_IO round {round_idx}] align=4k item={item} "
            f"disks={','.join(disks)} count={len(disks)} "
            f"parallel_models=16 peak_stress_qd_per_disk={peak_qd(plan)} "
            f"duration={duration_seconds}s remaining≈{remaining}s "
            f"stress={stress_runtime}s\n"
        )
        print(header)
        allure.dynamic.description(
            f"Round {round_idx}: align=4k 16 windows "
            f"FILL→STRESS({stress_runtime}s)→VERIFY，"
            f"同 bs+crc32c，seed={plan['seed']}，总时长={duration_seconds}s，"
            f"peak_stress_qd_per_disk={peak_qd(plan)}。"
        )
        attach_named_text(header, f"随机 IO 布局 (round {round_idx})")

        output = header
        for phase in PHASES:
            attach = phase == "VERIFY"
            try:
                output = run_and_check_argv(
                    ["fio", os.path.basename(jobs[phase])],
                    cwd=stress_dir,
                    extra_output=output
                    + f"[RANDOM_IO round {round_idx}] PHASE={phase} all 16 models together\n",
                    attach=attach,
                    attach_persistent_log=False,
                )
            except pytest.fail.Exception:
                if phase == "VERIFY":
                    result = format_consistency_result(
                        round_idx, len(disks), passed=False
                    )
                    print(result)
                    attach_named_text(
                        result + "\n", f"数据一致性结果 (round {round_idx})"
                    )
                raise
            if phase == "VERIFY":
                result = format_consistency_result(round_idx, len(disks), passed=True)
                print(result)
                attach_named_text(
                    result + "\n", f"数据一致性结果 (round {round_idx})"
                )

    if round_idx == 0:
        pytest.fail(
            f"RANDOM_IO_DURATION 过短，未能跑完至少一轮: {duration_seconds}s"
        )
    elapsed = max(0, int(time.monotonic() - started))
    print(
        f"[RANDOM_IO] finished rounds={round_idx} "
        f"budget={duration_seconds}s elapsed≈{elapsed}s align=4k "
        "(last round always completed after budget)"
    )
