import subprocess
import pytest
import allure
from datetime import datetime

def test_system_io_status():
    allure.dynamic.title("系统级 I/O 负载取样与分析 (iostat)")

    interval = "1"
    count = "10"
    iostat_cmd = ["iostat", "-m", "-x", interval, count]
    cmd_str = " ".join(iostat_cmd)

    # 在 Suites 视图中展示的执行步骤
    with allure.step(f"终端执行指令: {cmd_str}"):
        
        # 1. 模拟终端发送指令的日志记录
        send_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        send_log = f"{send_time} [SEND] {cmd_str}"
        print(send_log)

        # 2. 执行系统命令
        result = subprocess.run(iostat_cmd, capture_output=True, text=True)

        # 3. 模拟终端接收标准输出 (stdout) 的日志记录
        recv_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"{recv_time} [RECV] stdout:")
        print(result.stdout.strip())

        # 4. 如果有报错，记录标准错误 (stderr)
        if result.stderr:
            err_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"{err_time} [RECV] stderr:")
            print(result.stderr.strip())

        # (可选) 依然保留一份 txt 附件，方便一键下载原始日志
        allure.attach(
            f"{send_log}\n{recv_time} [RECV] stdout:\n{result.stdout}", 
            name="终端完整交互日志", 
            attachment_type=allure.attachment_type.TEXT
        )

    # 断言：非 0 则失败
    if result.returncode != 0:
        pytest.fail(f"指令执行失败，返回码: {result.returncode}")
