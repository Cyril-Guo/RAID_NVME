from .fio_helper import run_fio_test


def test_dc_powercycle():
    # 循环次数(FIO_CYCLES)与是否忽略错误(IGNORE_ERROR)均由 fio_helper 自动读取环境变量
    run_fio_test(item_type="dc", is_async=True)
