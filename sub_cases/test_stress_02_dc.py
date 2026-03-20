import os
from .fio_helper import run_fio_test

def test_dc_powercycle():
    # 从环境变量获取循环次数，默认为 10
    try:
        fio_cycles = os.environ.get("FIO_CYCLES", "10")
        loops = int(fio_cycles) if fio_cycles and fio_cycles.strip() else 10
    except ValueError:
        loops = 10
    # 从环境变量获取是否忽略错误，默认为 false
    ignore_error = os.environ.get("IGNORE_ERROR", "false").lower() == "true"
    
    # 调用统一的 FIO 执行函数
    run_fio_test(
        item_type="dc",
        loops=loops,
        is_async=True,
        stop_on_error=not ignore_error
    )
