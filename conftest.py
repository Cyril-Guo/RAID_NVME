import os
import sys

import pytest

try:
    import allure
except ImportError:
    class _NoopDynamic:
        def __getattr__(self, _name):
            return lambda *args, **kwargs: None

    class _NoopAttachmentType:
        TEXT = "text/plain"

    class _NoopAllure:
        dynamic = _NoopDynamic()
        attachment_type = _NoopAttachmentType()

        @staticmethod
        def attach(*args, **kwargs):
            return None

        @staticmethod
        def step(_title):
            class _Step:
                def __enter__(self):
                    return None

                def __exit__(self, exc_type, exc, tb):
                    return False

            return _Step()

    allure = _NoopAllure()
    sys.modules["allure"] = allure


@pytest.fixture(autouse=True)
def raid_nvme_run_context(record_xml_attribute):
    run_key = os.environ.get("RAID_NVME_RUN_KEY", "").strip()
    order = os.environ.get("RAID_NVME_RUN_ORDER", "").strip()
    item = os.environ.get("RAID_NVME_ITEM", "").strip()

    allure.dynamic.parent_suite("测试日志")
    if run_key:
        allure.dynamic.label("run_key", run_key)
        allure.dynamic.label("package", run_key)
        allure.dynamic.suite(run_key)
        if order:
            allure.dynamic.label("order", order)
        record_xml_attribute("classname", f"test_items.{run_key}")
    elif item:
        record_xml_attribute("classname", f"test_items.{item}")

    yield
