import pytest
import allure

@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item):
    allure.dynamic.parent_suite("测试日志")

