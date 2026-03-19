import os
from .fio_helper import run_fio_test

def test_specify_disks():
    # 从环境变量获取指定的磁盘，例如 "sdb,sdc"
    disks = os.environ.get("FIO_DISKS", "")
    args = ["-i", "lawdiskstress"] # 默认指定磁盘时也通常是进行裸盘压测
    if disks:
        args.extend(["-u", disks])
        
    run_fio_test(
        test_title="Specify Disks 测试",
        cmd_args=args,
        description=f"对指定的磁盘执行压测: {disks if disks else '默认所有磁盘'}"
    )
