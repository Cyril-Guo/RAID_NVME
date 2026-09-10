"""random_io plan generator — 4KiB-aligned block sizes only."""
from __future__ import annotations

from test_items.random_io_plan import *  # noqa: F403
from test_items.random_io_plan import (
    block_sizes_for_align,
    generate_random_io_plan as _generate_random_io_plan,
)

ALIGN = "4k"
BLOCK_SIZES = block_sizes_for_align("4k")


def generate_random_io_plan(seed=None, block_sizes=None):
    return _generate_random_io_plan(
        seed=seed, align=ALIGN, block_sizes=block_sizes or BLOCK_SIZES
    )
