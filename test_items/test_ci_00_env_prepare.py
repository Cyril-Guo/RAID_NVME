import allure

from test_items.basic_io_common import CommandLog, run_env_prepare


def test_env_prepare():
    allure.dynamic.title("Test_CI_env_prepare")
    allure.dynamic.description(
        "Physical DUT environment prepare (CI physical parity): "
        "stop QEMU if running, unload draid, return vfio devices to host, "
        "install dpraid, rebuild/reload draid, restore VD/PD."
    )

    log = CommandLog()
    try:
        log.write("Test_CI_env_prepare phase: run CI physical env prepare")
        run_env_prepare(log)
        log.write("Test_CI_env_prepare phase: done")
    finally:
        log.attach("env_prepare_commands")
