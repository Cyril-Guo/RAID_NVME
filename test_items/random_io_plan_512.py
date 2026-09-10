"""random_io plan generator — legacy/512 pool (previous behavior)."""
from __future__ import annotations

from test_items.random_io_plan import *  # noqa: F403
from test_items.random_io_plan import (
    BLOCK_SIZES_512,
    generate_random_io_plan as _generate_random_io_plan,
)

ALIGN = "512"
BLOCK_SIZES = BLOCK_SIZES_512


def generate_random_io_plan(seed=None, block_sizes=None):
    return _generate_random_io_plan(
        seed=seed, align=ALIGN, block_sizes=block_sizes or BLOCK_SIZES_512
    )
