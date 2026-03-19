from .fio_helper import run_fio_test

def test_mix_stress():
    run_fio_test(
        test_title="Mix 混合负载测试",
        cmd_args=["-mix", "yes"],
        description="启动混合 IO 模式的压力测试"
    )
