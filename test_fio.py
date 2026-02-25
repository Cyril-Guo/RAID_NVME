import subprocess
import json
import logging
import pytest
import allure
import os

# 配置日志，匹配 Jenkinsfile 中的 log_cli=true
logger = logging.getLogger(__name__)

def get_non_system_drives():
    """
    自动获取所有非系统盘的裸设备路径 (支持 nvme, sd*, vd* 等所有 disk 类型)
    """
    try:
        # 1. 找到挂载为根目录 (/) 的分区
        root_part = subprocess.check_output("findmnt -n -o SOURCE /", shell=True, text=True).strip()
        
        # 2. 找到该分区对应的物理磁盘 (如 /dev/sda1 -> sda, /dev/nvme0n1p1 -> nvme0n1)
        # 如果是 LVM 或复杂挂载，这里尝试获取最底层的物理盘
        root_disk = subprocess.check_output(f"lsblk -n -d -o PKNAME {root_part} 2>/dev/null", shell=True, text=True).strip()
        if not root_disk:
            # 如果没有父级块设备（例如本身就是裸盘挂载），则直接取设备名
            root_disk = root_part.split('/')[-1]

        # 3. 列出系统中所有类型为 "disk" 的块设备名 (自动排除光驱 rom、虚拟 loop 等)
        # lsblk 输出格式示例: sda disk \n nvme0n1 disk
        all_drives_output = subprocess.check_output("lsblk -d -n -o NAME,TYPE | awk '$2==\"disk\" {print $1}'", shell=True, text=True).strip()
        
        if not all_drives_output:
            logger.warning("未侦测到任何 disk 类型的物理磁盘！")
            return []

        all_drives = all_drives_output.split('\n')
        
        # 4. 过滤掉系统盘所在的那块物理盘
        test_drives = [f"/dev/{drive}" for drive in all_drives if drive and drive != root_disk]
        
        logger.info(f"侦测到系统挂载盘: {root_disk}")
        logger.info(f"侦测到可用于测试的非系统裸盘: {test_drives}")
        
        return test_drives

    except Exception as e:
        logger.error(f"获取磁盘信息失败: {e}")
        return []

# 动态获取可测试的磁盘列表
TARGET_DRIVES = get_non_system_drives()

# 定义要测试的读写模式
RW_MODES = ["read", "randread", "write", "randwrite"]

# ================= 测试用例区域 =================

@allure.epic("存储硬件基准测试")
@allure.feature("FIO 裸盘并发性能测试")
# 使用 pytest.mark.parametrize 自动为每块盘、每种模式生成一个独立测试用例
@pytest.mark.parametrize("drive", TARGET_DRIVES)
@pytest.mark.parametrize("rw_mode", RW_MODES)
def test_fio_performance(drive, rw_mode):
    # 动态设置 Allure 报告中的用例标题
    allure.dynamic.title(f"硬件基准测试: {drive} - 模式: {rw_mode}")
    
    # ⚠️ 危险操作安全锁：防止误将数据盘清空
    # 如果是写操作，且没有明确设置环境变量 ALLOW_DESTRUCTIVE_FIO=1，则跳过测试
    if "write" in rw_mode and os.environ.get("ALLOW_DESTRUCTIVE_FIO") != "1":
        pytest.skip("涉及破坏性写入测试（会清空磁盘数据）。如需执行，请在 Jenkins 环境变量中设置 ALLOW_DESTRUCTIVE_FIO=1")

    # FIO 参数配置 (可根据您公司对不同类型硬盘的压测标准进行微调)
    fio_cmd = [
        "sudo", "fio",
        f"--name=fio_{rw_mode}_test",
        f"--filename={drive}",
        f"--rw={rw_mode}",
        "--bs=4k",             # 块大小 4K，常用于测 IOPS
        "--ioengine=libaio",   # Linux 异步 IO 引擎
        "--iodepth=32",        # 队列深度 32
        "--numjobs=1",         # 线程数 1
        "--direct=1",          # 绕过系统 Buffer/Cache，测试裸盘真实性能
        "--size=1G",           # 测试范围 1G 空间
        "--runtime=10",        # 运行时间 10 秒
        "--time_based",        # 强制按时间运行满 10 秒
        "--output-format=json" # 输出为 JSON 方便 Python 解析
    ]

    cmd_str = " ".join(fio_cmd)
    logger.info(f"执行 FIO 命令: {cmd_str}")

    with allure.step(f"1. 对设备 {drive} 执行 FIO {rw_mode} 测试"):
        try:
            # 运行命令并捕获标准输出
            result = subprocess.run(fio_cmd, capture_output=True, text=True, check=True)
            fio_output = result.stdout
            
            # 将 FIO 的原始 JSON 输出作为附件保存到 Allure 报告中，方便深度排查
            allure.attach(fio_output, name="FIO_Raw_Output.json", attachment_type=allure.attachment_type.JSON)
            
        except subprocess.CalledProcessError as e:
            logger.error(f"FIO 执行失败:\n{e.stderr}")
            pytest.fail(f"FIO 命令执行失败，退出码: {e.returncode}")

    with allure.step("2. 解析性能指标并校验及格线"):
        try:
            # 解析 JSON 获取核心指标
            fio_data = json.loads(fio_output)
            job = fio_data["jobs"][0]
            
            # 区分读写模式提取对应的数据字典
            data_dict = job["write"] if "write" in rw_mode else job["read"]
            
            iops = float(data_dict["iops"])
            bw_kib = float(data_dict["bw"])             # 默认单位是 KiB/s
            bw_mib = bw_kib / 1024                      # 转换为 MiB/s
            lat_ns = float(data_dict["lat_ns"]["mean"]) # 平均延迟 纳秒
            lat_us = lat_ns / 1000                      # 转换为 微秒

            logger.info(f"[{drive} - {rw_mode}] 测得 IOPS: {iops:.2f}, 带宽: {bw_mib:.2f} MiB/s, 平均延迟: {lat_us:.2f} us")

            # 将核心指标以直观的文本形式附加到 Allure 步骤中
            allure.attach(
                f"设备: {drive}\n模式: {rw_mode}\n\n"
                f"► IOPS: {iops:.2f}\n"
                f"► Bandwidth: {bw_mib:.2f} MiB/s\n"
                f"► Latency (mean): {lat_us:.2f} us",
                name="核心性能概览",
                attachment_type=allure.attachment_type.TEXT
            )

            # ====== 性能及格线断言 (Pass/Fail) ======
            # 注意：由于现在混合了普通硬盘(sda)和NVMe硬盘，性能差异极大。
            # 如果你们有明确的标准，可以在这里写 if "nvme" in drive: ... else: ...
            
            # 通用基础断言示例：
            if rw_mode == "randread":
                # 假设所有做存储节点的数据盘，4K随机读不能低于 1000 IOPS
                assert iops >= 1000, f"[{drive}] 随机读 IOPS 太低! 期望 >= 1000，实际: {iops:.2f}"
            
            # 假设所有盘的平均读写延迟不应超过 20 毫秒 (20000 微秒)
            assert lat_us <= 20000, f"[{drive}] 平均延迟过高! 期望 <= 20000 us, 实际: {lat_us:.2f} us"

        except KeyError as e:
            pytest.fail(f"解析 FIO JSON 失败，FIO 版本可能不兼容，找不到键值: {e}")
        except AssertionError as e:
            pytest.fail(str(e))
