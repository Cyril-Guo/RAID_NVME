import pytest
from app import add

def test_add_success():
    assert add(10, 20) == 30

def test_add_fail():
    # 这是一个故意写错的测试，用来查看报告中的失败效果
    assert add(1, 1) == 3
