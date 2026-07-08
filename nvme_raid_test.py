import os
import sys
import pytest


# 测试项关键字 -> 测试文件（顺序即执行顺序）
TEST_ITEMS = {
    "reboot": "sub_cases/test_smoke_01_reboot.py",
    "dc": "sub_cases/test_smoke_02_dc.py",
    "lawdisk": "sub_cases/test_smoke_03_lawdisk.py",
    "filesystem": "sub_cases/test_smoke_04_filesystem.py",
    "mix": "sub_cases/test_smoke_05_mix.py",
    "restore": "sub_cases/test_smoke_07_restore.py",
}

# 测试项选择文件（与 target_ips.txt 风格一致）
ITEMS_FILE = "test_items.txt"


def parse_items_file(path):
    """
    解析 test_items.txt：
      - 纯关键字行  -> 加入待执行测试项
      - KEY=VALUE 行 -> 作为全局参数（注入环境变量）
      - 空行 / # 开头 -> 忽略
    返回 (selected_items, config)
    """
    selected_items = []
    config = {}

    if not os.path.exists(path):
        print(f"[WARN] 未找到测试项配置文件: {path}")
        return selected_items, config

    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                config[key.strip()] = val.strip()
            else:
                selected_items.append(line.lower())

    return selected_items, config


def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    items_path = os.path.join(base_dir, ITEMS_FILE)

    selected_items, config = parse_items_file(items_path)

    # 将 KEY=VALUE 配置注入环境变量，供 fio_helper / 各测试用例读取
    for key, val in config.items():
        os.environ[key] = val
        print(f"[CONFIG] {key}={val}")

    # 校验并提示未知测试项
    invalid = [i for i in selected_items if i not in TEST_ITEMS]
    if invalid:
        print(f"[WARN] 忽略未知测试项 {invalid}，可用项: {list(TEST_ITEMS.keys())}")

    # 按 TEST_ITEMS 定义顺序映射为测试文件
    selected_tests = [
        test_file for key, test_file in TEST_ITEMS.items() if key in selected_items
    ]

    if not selected_tests:
        print(f"未选择任何有效测试项，退出。请在 {ITEMS_FILE} 中取消注释需要执行的项。")
        return

    print(f"选择的测试项: {[i for i in selected_items if i in TEST_ITEMS]}")
    print(f"运行的测试文件: {selected_tests}")

    pytest_args = ["-v", "-s", "--tb=short", "--alluredir=allure-results", "--clean-alluredir"]
    pytest_args.extend(selected_tests)
    pytest_args.append("--junitxml=report.xml")

    sys.exit(pytest.main(pytest_args))


if __name__ == "__main__":
    main()
