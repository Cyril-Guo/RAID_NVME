import os
from .fio_helper import run_fio_test

def test_reboot_powercycle():
    # 从环境变量获取循环次数，默认为 100
    cycles = os.environ.get("FIO_CYCLES", "100")
    run_fio_test(
        test_title="Reboot Powercycle 测试",
        cmd_args=["-i", "reboot", "-l", cycles],
        description=f"执行 Reboot 模式下的 Powercycle 测试，当前循环次数: {cycles}"
    )
