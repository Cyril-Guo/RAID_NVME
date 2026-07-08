import os
import sys
import xml.etree.ElementTree as ET

import pytest


# 测试项关键字 -> 测试文件（字典顺序即执行顺序）
# 注：停止/清理(restore)已改由 Jenkins Web 的 RESTORE 选项处理，不再作为测试项。
TEST_ITEMS = {
    "reboot": "test_items/test_smoke_01_reboot.py",
    "dc": "test_items/test_smoke_02_dc.py",
    "lawdisk": "test_items/test_smoke_03_lawdisk.py",
    "filesystem": "test_items/test_smoke_04_filesystem.py",
    "mix": "test_items/test_smoke_05_mix.py",
}

# 各测试项各自"涉及"的参数白名单：块内写了白名单之外的参数会被忽略，
# 保证测试项与参数一一对应、互不影响。
ITEM_PARAMS = {
    # reboot / dc 的 FIO_CYCLES 表示电源循环次数，有实际意义。
    "reboot": ["FIO_CYCLES", "IGNORE_ERROR", "FIO_DISKS", "STRESS_MONITOR", "MONITOR_RUNTIME"],
    "dc": ["FIO_CYCLES", "IGNORE_ERROR", "FIO_DISKS", "STRESS_MONITOR", "MONITOR_RUNTIME"],
    # 压测项(lawdisk/filesystem/mix)的循环由 CSV 配置与 runtime 决定，
    # 底层 Fio_All.sh 会将 LOOP 固定为 1，故不涉及 FIO_CYCLES。
    "lawdisk": ["IGNORE_ERROR", "FIO_DISKS", "STRESS_MONITOR", "MONITOR_RUNTIME"],
    "filesystem": ["IGNORE_ERROR", "FIO_DISKS", "STRESS_MONITOR", "MONITOR_RUNTIME"],
    "mix": ["IGNORE_ERROR", "FIO_DISKS", "STRESS_MONITOR", "MONITOR_RUNTIME"],
}

# 所有可能被注入的参数（用于每项执行前清理上一项的残留）
ALL_PARAM_KEYS = sorted({k for keys in ITEM_PARAMS.values() for k in keys})

# 测试项选择文件
ITEMS_FILE = "test_items.txt"
ALLURE_DIR = "allure-results"
JUNIT_FINAL = "report.xml"


def parse_items_file(path):
    """
    解析 test_items.txt（单块式格式）：
      每个测试项对应一个 [item] 块，块内：
        enable = yes/no   该项唯一的开关（yes 才执行）
        其余 KEY = VALUE   为该项参数

    返回 (selected, params_map)：
      selected:   enable=yes 的测试项列表（按文件出现顺序）
      params_map: {item: {param: value}}（不含 enable）
    """
    selected = []
    params_map = {}
    current = None

    if not os.path.exists(path):
        print(f"[WARN] 未找到测试项配置文件: {path}")
        return selected, params_map

    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("[") and line.endswith("]"):
                current = line[1:-1].strip().lower()
                params_map.setdefault(current, {})
            elif "=" in line and current is not None:
                key, val = line.split("=", 1)
                key, val = key.strip(), val.strip()
                if key.lower() == "enable":
                    # enable 是块内唯一开关，不作为参数注入
                    if val.lower() == "yes":
                        selected.append(current)
                else:
                    params_map[current][key] = val

    return selected, params_map


def run_single_item(item, params, clean_allure):
    """
    为单个测试项注入其专属参数并执行对应的 pytest 文件。
    每项写出独立的 report_<item>.xml，稍后统一合并。
    返回该项的 pytest 退出码。
    """
    test_file = TEST_ITEMS[item]
    allowed = ITEM_PARAMS.get(item, [])

    # 清理上一项残留的参数，确保各项参数互不影响
    for key in ALL_PARAM_KEYS:
        os.environ.pop(key, None)

    print(f"\n{'=' * 60}")
    print(f"[ITEM] {item} -> {test_file}")
    for key, val in params.items():
        if key not in allowed:
            print(f"  [SKIP] {key}={val}（{item} 不涉及此参数，忽略）")
            continue
        os.environ[key] = val
        print(f"  [CONFIG] {key}={val}")

    pytest_args = ["-v", "-s", "--tb=short", f"--alluredir={ALLURE_DIR}"]
    if clean_allure:
        # 仅首个测试项清空历史 allure 结果，后续项追加
        pytest_args.append("--clean-alluredir")
    pytest_args.append(f"--junitxml=report_{item}.xml")
    pytest_args.append(test_file)

    return pytest.main(pytest_args)


def merge_junit_reports(items, out_path):
    """
    将各项的 report_<item>.xml 合并为单个 report.xml（<testsuites> 根节点），
    以兼容 Jenkinsfile 中对单一 report.xml 的采集与统计逻辑。
    """
    merged_root = ET.Element("testsuites")
    for item in items:
        part = f"report_{item}.xml"
        if not os.path.exists(part):
            continue
        try:
            root = ET.parse(part).getroot()
        except ET.ParseError:
            continue
        if root.tag == "testsuites":
            for suite in root.findall("testsuite"):
                merged_root.append(suite)
        elif root.tag == "testsuite":
            merged_root.append(root)

    ET.ElementTree(merged_root).write(out_path, encoding="utf-8", xml_declaration=True)


def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    items_path = os.path.join(base_dir, ITEMS_FILE)

    selected, params_map = parse_items_file(items_path)

    # 校验并提示未知测试项
    invalid = [item for item in selected if item not in TEST_ITEMS]
    if invalid:
        print(f"[WARN] 忽略未知测试项 {invalid}，可用项: {list(TEST_ITEMS.keys())}")

    # 已勾选且合法的测试项，按 TEST_ITEMS 定义顺序执行
    selected_set = {item for item in selected if item in TEST_ITEMS}
    run_order = [item for item in TEST_ITEMS if item in selected_set]

    if not run_order:
        print(f"未选择任何有效测试项，退出。请在 {ITEMS_FILE} 中把要执行的项的 enable 改为 yes。")
        return

    print(f"选择的测试项: {run_order}")

    exit_codes = []
    for idx, item in enumerate(run_order):
        code = run_single_item(item, params_map.get(item, {}), clean_allure=(idx == 0))
        exit_codes.append(int(code))

    # 合并各项 JUnit 报告为单一 report.xml
    merge_junit_reports(run_order, os.path.join(base_dir, JUNIT_FINAL))

    # 任一项失败则整体返回非零
    sys.exit(max(exit_codes) if exit_codes else 0)


if __name__ == "__main__":
    main()
