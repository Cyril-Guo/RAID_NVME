import subprocess
import pytest
import allure

def get_non_system_drives():
    """自动获取所有非系统盘的裸设备路径"""
    try:
        root_part = subprocess.check_output("findmnt -n -o SOURCE /", shell=True, text=True).strip()
        root_disk = subprocess.check_output(f"lsblk -n -d -o PKNAME {root_part} 2>/dev/null", shell=True, text=True).strip()
        if not root_disk:
            root_disk = root_part.split('/')[-1]

        all_drives_output = subprocess.check_output("lsblk -d -n -o NAME,TYPE | awk '$2==\"disk\" {print $1}'", shell=True, text=True).strip()
        
        if not all_drives_output:
            print("⚠️ 未侦测到任何 disk 类型的物理磁盘！")
            return []

        all_drives = all_drives_output.split('\n')
        test_drives = [f"/dev/{drive}" for drive in all_drives if drive and drive != root_disk]
        return test_drives
    except Exception as e:
        print(f"❌ 获取磁盘信息失败: {e}")
        return []

TARGET_DRIVES = get_non_system_drives()
RW_MODES = ["read", "randread"]

@allure.epic("存储硬件基准测试")
@allure.feature("读取性能与 SMART 健康自检")
@pytest.mark.parametrize("drive", TARGET_DRIVES)
@pytest.mark.parametrize("rw_mode", RW_MODES)
def test_read_and_smart(drive, rw_mode):
    # 恢复 Allure 漂亮的中文动态标题
    allure.dynamic.title(f"读取性能与SMART巡检: {drive} [{rw_mode}]")
    
    # print(f"\n{'='*60}\n🚀 开始测试设备: {drive} | 模式: {rw_mode}\n{'='*60}")
    
    # ---------------- 阶段 1: FIO 测试 ----------------
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
        "--time_based"
    ]
    
    cmd_str = " ".join(fio_cmd)
    
    with allure.step(f"1. 对设备 {drive} 执行 FIO {rw_mode} 测试"):
        print(f"\n▶️ [步骤 1] 正在执行 FIO 命令:\n$ {cmd_str}\n")
        # 捕获输出，不仅为了 Allure，也在控制台打印
        result = subprocess.run(fio_cmd, capture_output=True, text=True)
        fio_output = result.stdout + result.stderr
        # print(fio_output)
        
        # 将完整命令和终端输出贴到 Allure 报告右侧
        allure.attach(f"$ {cmd_str}\n\n{fio_output}", name="FIO 终端执行日志", attachment_type=allure.attachment_type.TEXT)
        
        if result.returncode != 0:
            pytest.fail("FIO 命令执行失败")

    # ---------------- 阶段 2: SMART 日志 ----------------
    smart_cmd = ["sudo", "smartctl", "-a", drive]
    smart_str = " ".join(smart_cmd)
    
    with allure.step(f"2. 提取 {drive} 的 SMART 监控日志"):
        print(f"\n▶️ [步骤 2] 正在执行 SMART 检测命令:\n$ {smart_str}\n")
        smart_result = subprocess.run(smart_cmd, capture_output=True, text=True)
        smart_output = smart_result.stdout + smart_result.stderr
        # print(smart_output)
        
        # 将 SMART 输出贴到 Allure 报告右侧
        allure.attach(f"$ {smart_str}\n\n{smart_output}", name="SMART 终端执行日志", attachment_type=allure.attachment_type.TEXT)

    # print(f"\n✅ {drive} [{rw_mode}] 测试流程结束。")
