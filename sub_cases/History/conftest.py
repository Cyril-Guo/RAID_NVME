import pytest

# 忽略该目录下的所有测试文件收集
def pytest_ignore_collect(path, config):
    return True
