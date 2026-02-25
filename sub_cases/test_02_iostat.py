import subprocess
import pytest
import allure

@allure.epic("存储硬件基准测试")
@allure.feature("系统级 I/O 负载监控")
def test_system_io_status():
    allure.dynamic.title("系统级 I/O 负载取样与分析 (iostat)")
    
    print(f"\n{'='*60}\n🚀 开始系统级 I/O 负载监控 (iostat)\n{'='*60}")
    
    interval = "1"
    count = "10"
    
    iostat_cmd = ["iostat", "-m", "-x", interval, count]
    cmd_str = " ".join(iostat_cmd)
    
    with allure.step(f"执行 iostat 命令连续取样 (间隔 {interval}s, 共 {count} 次)"):
        print(f"\n▶️ 正在执行 iostat 取样命令:\n$ {cmd_str}\n")
        
        result = subprocess.run(iostat_cmd, capture_output=True, text=True)
        io_output = result.stdout + result.stderr
        print(io_output)
        
        # 将完整命令和取样结果贴到 Allure 报告右侧
        allure.attach(f"$ {cmd_str}\n\n{io_output}", name="iostat 终端执行日志", attachment_type=allure.attachment_type.TEXT)
        
        if result.returncode != 0:
            print("\n❌ iostat 命令执行失败，请检查是否安装了 sysstat 工具。")
            pytest.fail("iostat 执行失败")
        else:
            print("\n✅ iostat 监控执行完毕。")
