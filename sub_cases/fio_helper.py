import os
import sys
import subprocess
import pytest
import allure
from datetime import datetime

_monitor_started = False


def _ts():
    """返回当前时间戳字符串，用于日志打印。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _env_int(name, default):
    """读取整数型环境变量，非法或为空时返回 default。"""
    raw = os.environ.get(name, "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _env_bool(name, default=False):
    """读取布尔型环境变量（true/false，大小写不敏感）。"""
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw == "true"


def start_stress_monitor():
    """根据环境变量 STRESS_MONITOR 开启后台压力监控工具。"""
    global _monitor_started
    if _monitor_started or not _env_bool("STRESS_MONITOR"):
        return

    monitor_runtime = os.environ.get("MONITOR_RUNTIME", "").strip()
    monitor_tool_dir = os.path.join(os.path.dirname(__file__), "Stress_Monitor_Tool")
    monitor_main = os.path.join(monitor_tool_dir, "main.py")

    if not os.path.exists(monitor_main):
        print(f"[{_ts()}] ⚠️  未找到监控工具: {monitor_main}")
        return

    # 使用绝对路径启动，便于后续 pkill -f 精准匹配
    cmd = [sys.executable, monitor_main]
    if monitor_runtime:
        cmd.extend(["-r", monitor_runtime])

    try:
        print(f"[{_ts()}] 📊 正在后台启动 Stress_Monitor_Tool (Runtime: {monitor_runtime or 'Default'})...")
        # cwd 设为工具目录，保证其相对路径(SITLib等)生效；
        # start_new_session 保证主测试结束后监控仍能按设定时长继续运行
        subprocess.Popen(
            cmd,
            cwd=monitor_tool_dir,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        _monitor_started = True
    except Exception as e:
        print(f"[{_ts()}] ❌ 启动监控工具失败: {e}")


def stop_stress_monitor():
    """停止后台压力监控工具，触发其生成报告。"""
    try:
        # 发送 SIGINT(2)，等同 Ctrl+C；main.py 捕获后走 finally 生成报告
        print(f"[{_ts()}] 🛑 正在停止 Stress_Monitor_Tool 并生成报告...")
        subprocess.run(["pkill", "-2", "-f", "Stress_Monitor_Tool/main.py"], check=False)
    except Exception as e:
        print(f"[{_ts()}] ❌ 停止监控工具失败: {e}")


def run_fio_test(item_type, loops=None, is_async=False, stop_on_error=None, mix_io=False):
    """
    运行 FIO 测试。

    :param item_type:    测试类型 (reboot, dc, lawdiskstress, filesystemstress, restore, ...)
    :param loops:        循环次数；None 时从环境变量 FIO_CYCLES 读取(默认 10)
    :param is_async:     是否异步执行(重启/掉电测试用，防止 SSH 断开报错)
    :param stop_on_error:出现 MachineCheck 错误时是否停止；None 时从 IGNORE_ERROR 读取
    :param mix_io:       是否启用混合 IO 模式(追加 --mix_io yes)
    """
    # 0. restore 项负责停止监控并生成报告；其余项按需启动监控
    if item_type.lower() == "restore":
        stop_stress_monitor()
    else:
        start_stress_monitor()

    # 1. 解析运行参数(未显式传入时回退到环境变量)
    if loops is None:
        loops = _env_int("FIO_CYCLES", 10)
    if stop_on_error is None:
        # IGNORE_ERROR=true 表示忽略错误继续 -> 不停止
        stop_on_error = not _env_bool("IGNORE_ERROR")
    flag_val = "STOP" if stop_on_error else "NON-STOP"

    # 2. 组装 Fio_All.sh 的命令行参数
    fio_args = ["-i", item_type, "-l", str(loops), "-f", flag_val]
    if mix_io:
        fio_args.extend(["--mix_io", "yes"])
    fio_disks = os.environ.get("FIO_DISKS", "").strip()
    if fio_disks:
        fio_args.extend(["-u", fio_disks])

    # 3. Allure 报告标题与描述
    allure.dynamic.title(f"FIO 测试: {item_type} (循环 {loops} 次)")
    allure.dynamic.description(
        f"执行 FIO 测试，类型为 '{item_type}'，循环 {loops} 次。"
        f"当出现 MachineCheck 错误时，{'停止' if stop_on_error else '不停止'}。"
    )

    # 4. 破坏性写入权限开关
    if os.environ.get("ALLOW_DESTRUCTIVE_FIO", "0") != "1":
        pytest.skip("ALLOW_DESTRUCTIVE_FIO 未开启，跳过破坏性 IO 测试")

    # 5. 执行脚本
    io_stress_dir = os.path.join(os.path.dirname(__file__), "test_items", "IO_Stress")
    fio_script = "./Fio_All.sh"
    cmd_str = f"bash {fio_script} {' '.join(fio_args)}"

    with allure.step(f"执行 FIO 指令: {cmd_str}"):
        print(f"{_ts()} [START] {cmd_str}")

        # 异步模式(重启/掉电)：setsid 触发后立即返回，避免 SSH 中断报错
        if is_async:
            async_cmd = f"setsid bash {fio_script} {' '.join(fio_args)} > /dev/null 2>&1 &"
            print("检测到重启/DC任务，采用异步触发模式...")
            subprocess.Popen(async_cmd, shell=True, cwd=io_stress_dir)
            print("测试已触发，正在安全退出 SSH 以防止连接中断报错...")
            return

        # 同步模式：实时透传输出
        process = subprocess.Popen(
            ["bash", fio_script] + fio_args,
            cwd=io_stress_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True,
        )

        full_output = []
        for line in process.stdout:
            timed_line = f"[{_ts()}] {line}"
            print(timed_line, end="")
            full_output.append(timed_line)

        process.wait()
        exit_code = process.returncode

        allure.attach(
            "".join(full_output),
            name="终端完整输出",
            attachment_type=allure.attachment_type.TEXT,
        )

        if exit_code != 0:
            print(f"{_ts()} [ERROR] 脚本执行失败，退出码: {exit_code}")
            pytest.fail(f"FIO 脚本执行失败，返回码: {exit_code}")
        print(f"{_ts()} [SUCCESS] 脚本执行完成")

    # 6. 结果汇总
    result_log = os.path.join(io_stress_dir, "log", "ResultLog", "result.log")
    if os.path.exists(result_log):
        with open(result_log, "r") as f:
            res_content = f.read()
        allure.attach(res_content, name="测试结果汇总", attachment_type=allure.attachment_type.TEXT)
        if "Fail" in res_content:
            pytest.fail("测试结果中检测到失败关键字")
