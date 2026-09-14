# Minimal pytest hooks for CLI branch.
import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "cli: CLI step-by-step case")
