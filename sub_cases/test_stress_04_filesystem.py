from .fio_helper import run_fio_test

def test_filesystemstress():
    run_fio_test(
        test_title="filesystemstress (文件系统压测)",
        cmd_args=["-i", "filesystemstress"],
        description="执行文件系统模式下的压力测试"
    )
