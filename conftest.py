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
    allure.dynamic.parent_suite("测试日志")

