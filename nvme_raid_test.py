import os
import sys
import pytest
from datetime import datetime

def main():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 🚀 开始执行 NVME RAID Test")
    
    # 定义子脚本存放的目录
    cases_dir = "sub_cases"
    
    if not os.path.exists(cases_dir):
        os.makedirs(cases_dir)
        print(f"❌ 错误: 未找到 {cases_dir} 目录，请在其中添加 test_*.py 子脚本！")
        sys.exit(1)

    # 组装 Pytest 执行参数
    # 支持从环境变量读取需要执行的具体测试项 (由 Jenkins 传入)
    test_files = []
    mapping = {
        "RUN_REBOOT": "sub_cases/test_stress_01_reboot.py",
        "RUN_DC": "sub_cases/test_stress_02_dc.py",
        "RUN_LAWDISK": "sub_cases/test_stress_03_lawdisk.py",
        "RUN_FILESYSTEM": "sub_cases/test_stress_04_filesystem.py",
        "RUN_MIX": "sub_cases/test_stress_05_mix.py",
        "RUN_SPECIFY": "sub_cases/test_stress_06_specify.py",
        "RUN_RESTORE": "sub_cases/test_stress_07_restore.py"
    }
    
    for env_var, file_path in mapping.items():
        if os.environ.get(env_var) == "true":
            test_files.append(file_path)
    
    # 如果没有任何勾选，则默认运行 sub_cases 下的所有有效用例
    if not test_files:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 未指定特定测试项，将运行所有子用例")
        test_files = [cases_dir]

    pytest_args = test_files + [
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
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 🏁 执行完毕，引擎退出码: {exit_code}")
    
    # 透传退出码给 Jenkins
    sys.exit(exit_code)

if __name__ == "__main__":
    main()
