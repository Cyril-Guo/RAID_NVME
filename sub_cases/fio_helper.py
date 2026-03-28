import os
import sys
import subprocess
import pytest
import allure
from datetime import datetime

_monitor_started = False

def start_stress_monitor():
    """
    根据环境变量 STRESS_MONITOR 开启后台压力监控工具
    """
    global _monitor_started
    if _monitor_started:
        return
    
    stress_monitor = os.environ.get("STRESS_MONITOR", "false").lower() == "true"
    if not stress_monitor:
        return

    monitor_runtime = os.environ.get("MONITOR_RUNTIME", "").strip()
    
    # 监控工具路径
    monitor_tool_dir = os.path.join(os.path.dirname(__file__), "Stress_Monitor_Tool")
    monitor_main = os.path.join(monitor_tool_dir, "main.py")
    
    if not os.path.exists(monitor_main):
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ⚠️  未找到监控工具: {monitor_main}")
        return

    # 构建启动命令：使用绝对路径，便于 pkill -f 精准匹配
    cmd_args = [sys.executable, monitor_main]
    if monitor_runtime:
        cmd_args.extend(["-r", monitor_runtime])
    
    try:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 📊 正在后台启动 Stress_Monitor_Tool (Runtime: {monitor_runtime or 'Default'})...")
        # 在工具目录下启动，以便其相对路径(SITLib等)生效
        subprocess.Popen(
            cmd_args,
            cwd=monitor_tool_dir,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True  # 确保监控进程在主测试完成后(或意外中断时)能继续运行一段时间(如果设置了时长)
        )
        _monitor_started = True
    except Exception as e:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ❌ 启动监控工具失败: {e}")

def stop_stress_monitor():
    """
    停止后台压力监控工具，触发其生成报告
    """
    try:
        # 使用 pkill 发送 SIGINT (2) 信号，等同于 Ctrl+C
        # Stress_Monitor_Tool/main.py 捕获该信号后会走 finally 生成报告
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 🛑 正在停止 Stress_Monitor_Tool 并生成报告...")
        # 改进 pkill 匹配逻辑，确保能精准搜寻到我们的监控进程
        subprocess.run(["pkill", "-2", "-f", "Stress_Monitor_Tool/main.py"], check=False)
    except Exception as e:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ❌ 停止监控工具失败: {e}")

def run_fio_test(item_type=None, loops=None, is_async=False, stop_on_error=True, **kwargs):
    """
    运行 FIO 测试
    :param item_type: 测试类型 (reboot, dc, lawdiskstress, filesystemstress, etc.)
    :param loops: 循环次数 (若为 None 则尝试从环境变量 FIO_CYCLES 获取，默认为 1)
    :param is_async: 是否异步执行 (用于重启测试，防止 SSH 断开报错)
    :param stop_on_error: 出现 MachineCheck 错误时是否停止 (True=STOP, False=NON-STOP)
    :param kwargs: 兼容旧版参数 (test_title, cmd_args, description)
    """
    # 0. 尝试启动或停止后台监控
    if item_type and item_type.lower() == "restore":
        stop_stress_monitor()
    else:
        start_stress_monitor()

    # 1. 兼容性处理：如果 item_type 没传，尝试从 cmd_args 中提取
    cmd_args_legacy = kwargs.get("cmd_args", [])
    if not item_type:
        if "-i" in cmd_args_legacy:
            idx = cmd_args_legacy.index("-i")
            item_type = cmd_args_legacy[idx+1]
        else:
            item_type = "lawdiskstress" # 默认值

    # 2. 循环次数处理：从参数或环境变量获取
    if loops is None:
        try:
            fio_cycles = os.environ.get("FIO_CYCLES", "10")
            loops = int(fio_cycles) if fio_cycles and fio_cycles.strip() else 10
        except ValueError:
            loops = 10
    
    # 3. 转换 stop_on_error 为脚本需要的参数
    flag_val = "STOP" if stop_on_error else "NON-STOP"
    
    # 4. 构建基础参数
    final_args = ["-i", item_type, "-l", str(loops), "-f", flag_val]
    
    # 如果有额外的命令行参数，也合并进去 (排除掉已经处理的 -i, -l, -f)
    for i in range(len(cmd_args_legacy)):
        if cmd_args_legacy[i] in ["-i", "-l", "-f"]:
            continue
        if i > 0 and cmd_args_legacy[i-1] in ["-i", "-l", "-f"]:
            continue
        final_args.append(cmd_args_legacy[i])
 
    # 5. 处理指定磁盘参数 (FIO_DISKS)
    # 如果环境变量中有 FIO_DISKS，且 final_args 或 cmd_args_legacy 中没传 -u，则自动添加
    fio_disks = os.environ.get("FIO_DISKS", "").strip()
    if fio_disks and "-u" not in final_args and "-u" not in cmd_args_legacy:
        final_args.extend(["-u", fio_disks])

    # Allure 报告标题和描述
    allure.dynamic.title(f"FIO 测试: {item_type} (循环 {loops} 次)")
    allure.dynamic.description(f"执行 FIO 测试，类型为 '{item_type}'，循环 {loops} 次。当出现 MachineCheck 错误时，{'停止' if stop_on_error else '不停止'}。")
    
    # 1. 检查权限开关
    allow_destructive = os.environ.get("ALLOW_DESTRUCTIVE_FIO", "0")
    if allow_destructive != "1":
        pytest.skip("ALLOW_DESTRUCTIVE_FIO 未开启，跳过破坏性 IO 测试")

    # 2. 准备路径
    io_stress_dir = os.path.join(os.path.dirname(__file__), "IO_Stress")
    fio_script = "./Fio_All.sh"
    
    cmd_str = f"bash {fio_script} {' '.join(final_args)}"

    with allure.step(f"执行 FIO 指令: {cmd_str}"):
        send_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"{send_time} [START] {cmd_str}")
        
        # 3. 执行脚本
        if is_async:
            # 异步模式下，使用 setsid 触发后立即退出
            async_cmd = f"setsid bash {fio_script} {' '.join(final_args)} > /dev/null 2>&1 &"
            print(f"检测到重启/DC任务，采用异步触发模式...")
            subprocess.Popen(async_cmd, shell=True, cwd=io_stress_dir)
            print(f"测试已触发，正在安全退出 SSH 以防止连接中断报错...")
            return

        process = subprocess.Popen(
            ["bash", fio_script] + final_args,
            cwd=io_stress_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True
        )

        full_output = []
        for line in process.stdout:
            timestamp = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
            timed_line = f"{timestamp} {line}"
            print(timed_line, end="")
            full_output.append(timed_line)
        
        process.wait()
        exit_code = process.returncode
        recv_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 4. 记录日志到 Allure
        output_text = "".join(full_output)
        allure.attach(
            output_text,
            name="终端完整输出",
            attachment_type=allure.attachment_type.TEXT
        )

        if exit_code != 0:
            print(f"{recv_time} [ERROR] 脚本执行失败，退出码: {exit_code}")
            # 记录回传错误日志
            pytest.fail(f"FIO 脚本执行失败，返回码: {exit_code}")
        else:
            print(f"{recv_time} [SUCCESS] 脚本执行完成")

    # 5. 结果汇总
    result_log = os.path.join(io_stress_dir, "log", "ResultLog", "result.log")
    if os.path.exists(result_log):
        with open(result_log, 'r') as f:
            res_content = f.read()
            allure.attach(res_content, name="测试结果汇总", attachment_type=allure.attachment_type.TEXT)
            if "Fail" in res_content:
                pytest.fail("测试结果中检测到失败关键字")
