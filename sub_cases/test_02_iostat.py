import subprocess
import pytest

def test_system_io_status():
    print(f"\n" + "="*60)
    print("🚀 开始系统级 I/O 负载监控 (iostat)")
    print("="*60)
    
    interval = "1"
    count = "10"
    
    iostat_cmd = ["iostat", "-m", "-x", interval, count]
    cmd_str = " ".join(iostat_cmd)
    
    print(f"\n▶️ 正在执行 iostat 取样命令 (每秒1次，共10次):\n$ {cmd_str}\n")
    
    # 实时打印执行结果
    try:
        subprocess.run(iostat_cmd, check=True)
        print("\n✅ iostat 监控执行完毕。")
    except subprocess.CalledProcessError:
        print("\n❌ iostat 命令执行失败，请检查被测机是否安装了 sysstat 工具。")
        pytest.fail("iostat 执行失败")
