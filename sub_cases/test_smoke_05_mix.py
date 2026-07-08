from .fio_helper import run_fio_test


def test_mix_stress():
    run_fio_test(item_type="lawdiskstress", mix_io=True)
