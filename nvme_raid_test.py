import os
import sys
import glob
import pytest
from datetime import datetime

def main():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 🚀 开始执行 NVME RAID Test 动态扫描引擎")

    # 1. 基础 pytest 参数 (不包含 'pytest' 命令本身)
    pytest_args = [
        "-v",
        "-s",
        "--alluredir=allure-results",
        "--clean-alluredir"
    ]

    # 2. 动态扫描 sub_cases 目录下的所有以 test_ 开头的 python 文件
    sub_cases_dir = "sub_cases"
    if not os.path.exists(sub_cases_dir):
        print(f"❌ 错误: 未找到 {sub_cases_dir} 目录")
        sys.exit(1)

    test_files = glob.glob(os.path.join(sub_cases_dir, "test_*.py"))
    
    # 3. 确定哪些用例需要运行
    selected_files = []
    
    for f in sorted(test_files):
        filename = os.path.basename(f)     # e.g. test_stress_01_reboot.py
        name_parts = filename.replace(".py", "").split("_")
        
        # 尝试提取关键标识（取最后一个部分并转大写）
        # test_stress_01_reboot -> REBOOT
        key = name_parts[-1].upper()
        env_var_name = f"RUN_{key}"
        
        should_run = True
        # 检查是否有明确的禁止信号 (Jenkins 传入 RUN_XXX=false)
        if env_var_name in os.environ:
            val = os.environ.get(env_var_name, "").lower()
            if val == "false":
                should_run = False
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ⏭️  跳过用例: {filename} (由 {env_var_name}=false 指定)")
        
        if should_run:
            selected_files.append(f)

    if not selected_files:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ⚠️  未发现匹配的测试用例！")
        sys.exit(0)

    pytest_args.extend(selected_files)

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 正在执行: pytest {' '.join(pytest_args)}")
    
    # 执行 pytest
    exit_code = pytest.main(pytest_args)
    
    print("="*50)
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 🏁 执行完毕，引擎退出码: {exit_code}")
    
    # 透传退出码给 Jenkins
    sys.exit(exit_code)

if __name__ == "__main__":
    main()
