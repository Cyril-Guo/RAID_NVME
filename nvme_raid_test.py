import os
import sys
import pytest
from datetime import datetime

def main():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 🚀 开始执行 NVME RAID 母测试脚本")
    
    # 定义子脚本存放的目录
    cases_dir = "sub_cases"
    
    if not os.path.exists(cases_dir):
        os.makedirs(cases_dir)
        print(f"❌ 错误: 未找到 {cases_dir} 目录，请在其中添加 test_*.py 子脚本！")
        sys.exit(1)

    # 组装 Pytest 执行参数
    # -s: 允许子脚本中的 print 语句直接穿透打印到控制台
    # --alluredir / --junitxml: 统一收集所有子脚本的测试结果
    pytest_args = [
        cases_dir,
        "--alluredir=./allure-results",
        "--junitxml=report.xml",
        "-o", "log_cli=true",
        "-o", "log_cli_level=INFO",
        "-s", 
        "-v"
    ]
    
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 正在调度子脚本执行...")
    print(f"执行参数: pytest {' '.join(pytest_args)}\n" + "="*50)
    
    # 核心调用：执行所有的子脚本
    exit_code = pytest.main(pytest_args)
    
    print("="*50)
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 🏁 母脚本执行完毕，引擎退出码: {exit_code}")
    
    # 透传退出码给 Jenkins
    sys.exit(exit_code)

if __name__ == "__main__":
    main()
