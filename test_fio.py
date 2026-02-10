import pytest
import subprocess
import logging
import allure

# 配置测试目标和模式
DEVICES = ["nvme0n1", "nvme1n1", "nvme8n1"]
TEST_MODES = [
    ("随机写", "randwrite"),
]

@allure.suite("测试日志")
@allure.feature("NVMe FIO 性能测试")
@allure.severity(allure.severity_level.NORMAL)
@pytest.mark.parametrize("device", DEVICES)
@pytest.mark.parametrize("mode_name, fio_rw", TEST_MODES)
def test_nvme_performance(device, mode_name, fio_rw):
    """
    针对指定 NVMe 设备执行 FIO 性能测试
    """

    logging.info(f"开始测试设备: /dev/{device} | 模式: {mode_name}")

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

    process = subprocess.run(cmd, capture_output=True, text=True)

    allure.attach(
        process.stdout,
        name="FIO stdout",
        attachment_type=allure.attachment_type.TEXT
    )

    if process.returncode != 0:
        allure.attach(
            process.stderr,
            name="FIO stderr",
            attachment_type=allure.attachment_type.TEXT
        )
        pytest.fail(
            f"设备 {device} 在 {mode_name} 模式下执行失败",
            pytrace=False
        )

    if "iops" not in process.stdout.lower():
        pytest.fail(
            "未在输出中检测到 IOPS 统计数据",
            pytrace=False
        )

