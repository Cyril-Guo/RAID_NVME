import os
import subprocess
import pytest
import allure
from datetime import datetime

def run_fio_test(test_title, cmd_args, description=""):
    """
    通用 FIO 测试执行函数
    :param test_title: Allure 报告中的显示标题
    :param cmd_args: 传给 Fio_All.sh 的参数列表
    :param description: 测试描述
    """
    allure.dynamic.title(test_title)
    if description:
        allure.dynamic.description(description)
    
    # 1. 检查权限开关
    allow_destructive = os.environ.get("ALLOW_DESTRUCTIVE_FIO", "0")
    if allow_destructive != "1":
        pytest.skip("ALLOW_DESTRUCTIVE_FIO 未开启，跳过破坏性 IO 测试")

    # 2. 准备路径
    # 假设 helper 在 sub_cases/ 下，项目根目录是其上一级
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    io_stress_dir = os.path.join(base_dir, "sub_cases", "IO_Stress")
    fio_script = "./Fio_All.sh"
    
    cmd = ["bash", fio_script] + cmd_args
    cmd_str = " ".join(cmd)

    with allure.step(f"执行 FIO 指令: {cmd_str}"):
        send_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"{send_time} [START] {cmd_str}")
        
        # 3. 执行脚本
        process = subprocess.Popen(
            cmd,
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
            # 尝试查找错误日志文件
            error_log_path = os.path.join(io_stress_dir, "log", "TestErrorLog")
            if os.path.exists(error_log_path):
                try:
                    for ef in os.listdir(error_log_path):
                        with open(os.path.join(error_log_path, ef), 'r') as f:
                            allure.attach(f.read(), name=f"错误日志_{ef}", attachment_type=allure.attachment_type.TEXT)
                except: pass
            
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
