import os
import sys
import pytest
from datetime import datetime

def main():
    # 基础 pytest 参数
    pytest_args = [
        "pytest",
        "-v",
        "-s",
        "--alluredir=allure-results",
        "--clean-alluredir"
    ]
    
    # 核心调用：执行所有的子脚本
    exit_code = pytest.main(pytest_args)
    
    print("="*50)
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 🏁 执行完毕，引擎退出码: {exit_code}")
    
    # 透传退出码给 Jenkins
    sys.exit(exit_code)

if __name__ == "__main__":
    main()
