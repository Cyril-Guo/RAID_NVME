import os

import allure
import pytest

from test_items.basic_io_common import CommandLog, prepare_basic_raid5_vds
from test_items import test_smoke_03_lawdisk as lawdisk_case


def test_basic_io():
    allure.dynamic.title("Test_Smoke_06_basic_IO")
    allure.dynamic.description(
        "Delete existing VDs, discover and format non-system NVMe disks, add PDs, create eight "
        "RAID5 VDs, show PD/VD information, then run lawdisk FIO."
    )

    if os.environ.get("ALLOW_DESTRUCTIVE_FIO", "0") != "1":
        pytest.skip("ALLOW_DESTRUCTIVE_FIO is not enabled; skip destructive basic IO test")

    log = CommandLog()
    try:
        log.write("Test_Smoke_06_basic_IO phase: prepare RAID5 VDs")
        prepare_basic_raid5_vds(log)
        log.write("Test_Smoke_06_basic_IO phase: start lawdisk FIO")
    finally:
        log.attach("Test_Smoke_06_basic_IO_terminal_output")

    lawdisk_case.test_lawdiskstress()
