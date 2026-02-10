import pytest
import subprocess
import logging
import allure

@allure.suite("测试日志")
@allure.parent_suite("测试日志")

# 配置测试目标和模式
DEVICES = ["nvme0n1", "nvme1n1", "nvme8n1"]
TEST_MODES = [
    #("顺序读", "read"),
    #("顺序写", "write"),
    #("随机读", "randread"),
    ("随机写", "randwrite")
]

@pytest.mark.parametrize("device", DEVICES)
@pytest.mark.parametrize("mode_name, fio_rw", TEST_MODES)
def test_nvme_performance(device, mode_name, fio_rw):
    """
    针对指定 NVMe 设备执行 FIO 性能测试
    """
    logging.info(f"开始测试设备: /dev/{device} | 模式: {mode_name}")
    
    # 构造 FIO 命令
    # --runtime=30 持续30秒
    # --direct=1 绕过缓存
    cmd = [
        "fio",
        f"--name={device}_{fio_rw}",
        f"--filename=/dev/{device}",
        f"--rw={fio_rw}",
        "--direct=1",
        "--bs=4k",
        "--ioengine=libaio",
        "--iodepth=64",
        "--runtime=30",
        "--time_based",
        "--group_reporting"
    ]
    
    # 执行命令并捕获输出
    process = subprocess.run(cmd, capture_output=True, text=True)
    
    # 将详细日志输出，供 Allure 捕获并在可视化界面显示
    logging.info(f"FIO 执行结果:\n{process.stdout}")
    
    if process.returncode != 0:
        logging.error(f"FIO 执行失败:\n{process.stderr}")
        assert False, f"设备 {device} 在 {mode_name} 模式下执行失败"
    
    # 简单断言：确保输出中包含关键性能指标
    assert "iops" in process.stdout.lower(), "未在输出中找到 IOPS 统计数据"
