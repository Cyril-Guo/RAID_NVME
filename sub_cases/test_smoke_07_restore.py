from .fio_helper import run_fio_test

def test_cancel_restore():
    run_fio_test(item_type="restore")
