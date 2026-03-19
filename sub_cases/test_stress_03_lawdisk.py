from .fio_helper import run_fio_test

def test_lawdiskstress():
    run_fio_test(
        test_title="lawdiskstress (裸盘压测)",
        cmd_args=["-i", "lawdiskstress"],
        description="执行默认的裸盘压力测试"
    )
