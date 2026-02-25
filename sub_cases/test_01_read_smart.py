import subprocess
import pytest

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
        
        print(f"🔍 排除系统盘 ({root_disk})，发现目标测试盘: {test_drives}")
        return test_drives

    except Exception as e:
        print(f"❌ 获取磁盘信息失败: {e}")
        return []

TARGET_DRIVES = get_non_system_drives()
RW_MODES = ["read", "randread"]

@pytest.mark.parametrize("drive", TARGET_DRIVES)
@pytest.mark.parametrize("rw_mode", RW_MODES)
def test_read_and_smart(drive, rw_mode):
    print(f"\n" + "="*60)
    print(f"🚀 开始测试设备: {drive} | 模式: {rw_mode}")
    print("="*60)
    
    # ---------------- 阶段 1: FIO 测试 ----------------
    # 移除了 --output-format=json，让终端直接打印人类可读的 FIO 报告
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
    print(f"\n▶️ [步骤 1] 正在执行 FIO 命令:\n$ {cmd_str}\n")
    
    # 不使用 capture_output=True，让输出直接实时流向终端/日志
    subprocess.run(fio_cmd, check=True)

    # ---------------- 阶段 2: SMART 日志 ----------------
    smart_cmd = ["sudo", "smartctl", "-a", drive]
    smart_cmd_str = " ".join(smart_cmd)
    
    print(f"\n▶️ [步骤 2] 正在执行 SMART 检测命令:\n$ {smart_cmd_str}\n")
    
    # 同样不拦截输出，直接打印到控制台
    subprocess.run(smart_cmd)
    
    print(f"\n✅ {drive} [{rw_mode}] 测试流程结束。")
