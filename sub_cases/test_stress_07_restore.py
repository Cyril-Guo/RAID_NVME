from .fio_helper import run_fio_test

def test_cancel_restore():
    run_fio_test(
        test_title="Cancel & Restore (清理环境)",
        cmd_args=["-i", "restore"],
        description="中途取消测试并清理测试环境（包括自启动项等）"
    )
