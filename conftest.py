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


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item):
    run_key = os.environ.get("RAID_NVME_RUN_KEY", "").strip()
    order = os.environ.get("RAID_NVME_RUN_ORDER", "").strip()
    case_item = os.environ.get("RAID_NVME_ITEM", "").strip()

    allure.dynamic.parent_suite("测试日志")
    if run_key:
        allure.dynamic.label("run_key", run_key)
        allure.dynamic.label("package", run_key)
        allure.dynamic.suite(run_key)
        if order:
            allure.dynamic.label("order", order)
        item.user_properties.append(("run_key", run_key))
    elif case_item:
        item.user_properties.append(("run_key", case_item))
