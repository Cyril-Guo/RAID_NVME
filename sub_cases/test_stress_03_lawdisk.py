from .fio_helper import run_fio_test

def test_lawdiskstress():
    run_fio_test(item_type="lawdiskstress")
