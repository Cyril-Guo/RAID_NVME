import os
import subprocess
import pytest
import allure
from datetime import datetime

def run_fio_test(item_type, loops=10, is_async=False, stop_on_error=True):
    """
    运行 FIO 测试
    :param item_type: 测试类型 (reboot, dc, lawdisk, etc.)
    :param loops: 循环次数
    :param is_async: 是否异步执行 (用于重启测试，防止 SSH 断开报错)
    :param stop_on_error: 出现 MachineCheck 错误时是否停止 (True=STOP, False=NON-STOP)
    """
    # 转换 stop_on_error 为脚本需要的参数
    flag_val = "STOP" if stop_on_error else "NON-STOP"
    
    # 基础参数
    cmd_args = [
        "-i", item_type,
        "-l", str(loops),
        "-f", flag_val
    ]

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
    
    cmd_str = f"bash {fio_script} {' '.join(cmd_args)}"

    with allure.step(f"执行 FIO 指令: {cmd_str}"):
        send_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"{send_time} [START] {cmd_str}")
        
        # 3. 执行脚本
        if is_async:
            # 异步模式下，使用 setsid 触发后立即退出
            async_cmd = f"setsid bash {fio_script} {' '.join(cmd_args)} > /dev/null 2>&1 &"
            print(f"检测到重启/DC任务，采用异步触发模式...")
            subprocess.Popen(async_cmd, shell=True, cwd=io_stress_dir)
            print(f"测试已触发，正在安全退出 SSH 以防止连接中断报错...")
            return

        process = subprocess.Popen(
            ["bash", fio_script] + cmd_args,
            cwd=io_stress_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True
        )

        full_output = []
        for line in process.stdout:
            print(line, end="")
            full_output.append(line)
        
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
