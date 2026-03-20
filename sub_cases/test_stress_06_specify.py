import os
from .fio_helper import run_fio_test

def test_specify_disks():
    # 从环境变量获取指定的磁盘，例如 "sdb,sdc"
    disks = os.environ.get("FIO_DISKS", "")
    args = ["-i", "lawdiskstress"] # 默认指定磁盘时也通常是进行裸盘压测
    if disks:
        args.extend(["-u", disks])
        
    run_fio_test(
        item_type="lawdiskstress",
        cmd_args=args
    )
