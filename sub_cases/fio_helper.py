import os
import subprocess
import pytest
import allure
from datetime import datetime

def run_fio_test(item_type=None, loops=None, is_async=False, stop_on_error=True, **kwargs):
    """
    运行 FIO 测试
    :param item_type: 测试类型 (reboot, dc, lawdiskstress, filesystemstress, etc.)
    :param loops: 循环次数 (若为 None 则尝试从环境变量 FIO_CYCLES 获取，默认为 1)
    :param is_async: 是否异步执行 (用于重启测试，防止 SSH 断开报错)
    :param stop_on_error: 出现 MachineCheck 错误时是否停止 (True=STOP, False=NON-STOP)
    :param kwargs: 兼容旧版参数 (test_title, cmd_args, description)
    """
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
            fio_cycles = os.environ.get("FIO_CYCLES", "1")
            loops = int(fio_cycles) if fio_cycles and fio_cycles.strip() else 1
        except ValueError:
            loops = 1
    
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
