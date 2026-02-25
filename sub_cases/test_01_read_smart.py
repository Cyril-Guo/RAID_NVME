import subprocess
import json
import logging
import pytest
import allure

logger = logging.getLogger(__name__)

def get_non_system_drives():
    """
    自动获取所有非系统盘的裸设备路径 (支持 nvme, sd*, vd* 等所有 disk 类型)
    """
    try:
        root_part = subprocess.check_output("findmnt -n -o SOURCE /", shell=True, text=True).strip()
        
        root_disk = subprocess.check_output(f"lsblk -n -d -o PKNAME {root_part} 2>/dev/null", shell=True, text=True).strip()
        if not root_disk:
            root_disk = root_part.split('/')[-1]

        all_drives_output = subprocess.check_output("lsblk -d -n -o NAME,TYPE | awk '$2==\"disk\" {print $1}'", shell=True, text=True).strip()
        
        if not all_drives_output:
            logger.warning("未侦测到任何 disk 类型的物理磁盘！")
            return []

        all_drives = all_drives_output.split('\n')
        test_drives = [f"/dev/{drive}" for drive in all_drives if drive and drive != root_disk]
        
        logger.info(f"侦测到系统挂载盘: {root_disk}")
        logger.info(f"侦测到可用于测试的非系统裸盘: {test_drives}")
        
        return test_drives

    except Exception as e:
        logger.error(f"获取磁盘信息失败: {e}")
        return []

# 动态获取目标盘
TARGET_DRIVES = get_non_system_drives()

# 本脚本仅执行读测试（顺序读 read，随机读 randread）
RW_MODES = ["read", "randread"]

@allure.epic("存储硬件基准测试")
@allure.feature("读取性能与 SMART 健康状态自检")
@pytest.mark.parametrize("drive", TARGET_DRIVES)
@pytest.mark.parametrize("rw_mode", RW_MODES)
def test_read_and_smart(drive, rw_mode):
    allure.dynamic.title(f"读取性能与SMART巡检: {drive} [{rw_mode}]")
    
    # ================= 阶段 1：FIO 读取性能测试 =================
    fio_cmd = [
        "sudo", "fio",
        f"--name=fio_{rw_mode}_test",
        f"--filename={drive}",
        f"--rw={rw_mode}",
        "--bs=4k",             
        "--ioengine=libaio",   
        "--iodepth=32",        
        "--numjobs=1",         
        "--direct=1",          
        "--size=1G",           
        "--runtime=10",        
        "--time_based",        
        "--output-format=json" 
    ]

    with allure.step(f"1. 对设备 {drive} 执行 FIO {rw_mode} 测试"):
        try:
            logger.info(f"开始 FIO 测试: {' '.join(fio_cmd)}")
            result = subprocess.run(fio_cmd, capture_output=True, text=True, check=True)
            fio_output = result.stdout
            
            # 将 FIO JSON 日志作为附件
            allure.attach(fio_output, name="FIO_Raw_Output.json", attachment_type=allure.attachment_type.JSON)
            
            # 解析只读指标
            fio_data = json.loads(fio_output)
            read_data = fio_data["jobs"][0]["read"]
            
            iops = float(read_data["iops"])
            bw_mib = float(read_data["bw"]) / 1024
            lat_us = float(read_data["lat_ns"]["mean"]) / 1000

            logger.info(f"[{drive} - {rw_mode}] IOPS: {iops:.2f}, 带宽: {bw_mib:.2f} MiB/s, 延迟: {lat_us:.2f} us")

            allure.attach(
                f"设备: {drive}\n模式: {rw_mode}\n\n► IOPS: {iops:.2f}\n► 带宽: {bw_mib:.2f} MiB/s\n► 平均延迟: {lat_us:.2f} us",
                name="读取性能概览",
                attachment_type=allure.attachment_type.TEXT
            )

            # 基础读性能断言（请根据实际硬件水准调整）
            assert iops >= 500, f"[{drive}] 读取 IOPS 过低! 实际: {iops:.2f}"
            assert lat_us <= 30000, f"[{drive}] 读取延迟过高! 实际: {lat_us:.2f} us"

        except Exception as e:
            pytest.fail(f"FIO 读取测试异常: {e}")

    # ================= 阶段 2：获取 SMART 健康日志 =================
    with allure.step(f"2. 提取 {drive} 的 SMART 监控日志"):
        try:
            # 运行 smartctl 获取所有健康信息 (-a 代表 all)
            # 注意: smartctl 在发现部分小瑕疵时可能会返回非 0 状态码，因此 check=False
            logger.info(f"正在提取 {drive} 的 SMART 日志...")
            smart_res = subprocess.run(["sudo", "smartctl", "-a", drive], capture_output=True, text=True)
            smart_output = smart_res.stdout + smart_res.stderr

            if "command not found" in smart_output.lower():
                pytest.skip("目标机未安装 smartmontools 无法执行 smartctl，请先通过 apt/yum 安装。")

            # 将完整的 SMART 日志作为文本附件挂载到 Allure 报告中
            allure.attach(
                smart_output, 
                name=f"SMART_LOG_{drive.split('/')[-1]}.txt", 
                attachment_type=allure.attachment_type.TEXT
            )

            # 简单校验：判断日志中是否包含 PASSED 或 OK 关键字 (适用于大多数盘)
            if "PASSED" in smart_output.upper() or "OK" in smart_output.upper():
                logger.info(f"{drive} SMART 自检健康状态: 通过")
            else:
                logger.warning(f"{drive} SMART 日志中未找到明确的 PASSED 标识，请打开 Allure 附件人工核查！")

        except Exception as e:
            logger.error(f"提取 SMART 日志时发生异常: {e}")
            allure.attach(str(e), name="SMART提取异常", attachment_type=allure.attachment_type.TEXT)
