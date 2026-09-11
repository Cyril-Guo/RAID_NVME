#!/usr/bin/env python3
"""Mix IO model for mix_512 — pre-split base (2f19976) with memory-safe large-bs trim.

Dropped (>~5–6MiB peak risk / very large): 8m, 16m, 6145k, 7169k, 10241k, 12289k.
Their 8% weight moved to eight 512-aligned boundary sizes (often not 4KiB-aligned)
to stress RMW / split-IO near power-of-two edges while keeping bs 512-aligned.
Max remaining large: 5121k (~5MiB) → ~160GiB peak @32 disks ×4 MixIO ×QD32 ×jobs8 (under 180GiB).

All block sizes are 512-byte aligned. Weights sum to 100. Generates MixIO CSV with total=1000 rows, each model runtime=30s.
"""
from __future__ import annotations

import copy
import random


def _bs_bytes(label: str) -> int:
    text = label.strip().lower()
    if text.endswith("k"):
        return int(text[:-1]) * 1024
    if text.endswith("m"):
        return int(text[:-1]) * 1024 * 1024
    if text.endswith("b"):
        return int(text[:-1])
    return int(text)


temp_dict = {
    "512b": 4,
    "1k": 1,
    "1536b": 4,
    "2k": 1,
    "2560b": 1,
    "3k": 2,
    "3584b": 1,
    "4k": 19,
    "8k": 6,
    "16k": 5,
    "32k": 3,
    "64k": 3,
    "1m": 2,
    "2m": 2,
    "4m": 2,
    # removed: 8m, 16m (was 2+2) — memory
    # +40 mid/large non-4k-aligned (trimmed: drop 6145k/7169k/10241k/12289k)
    "5k": 1,
    "6k": 1,
    "7k": 1,
    "9k": 1,
    "10k": 1,
    "11k": 1,
    "12k": 1,
    "13k": 1,
    "14k": 1,
    "15k": 1,
    "17k": 1,
    "18k": 1,
    "20k": 1,
    "25k": 1,
    "29k": 1,
    "37k": 1,
    "41k": 1,
    "49k": 1,
    "57k": 1,
    "73k": 1,
    "81k": 1,
    "97k": 1,
    "113k": 1,
    "129k": 1,
    "161k": 1,
    "193k": 1,
    "225k": 1,
    "257k": 1,
    "321k": 1,
    "385k": 1,
    "449k": 1,
    "513k": 1,
    "769k": 1,
    "897k": 1,
    "3073k": 1,
    "5121k": 1,
    # 8% freed from 8m/16m/6145k/7169k/10241k/12289k →
    # 512-aligned boundary sizes near old unaligned edges (not 4KiB-aligned)
    "4608b": 1,   # was 4095b → 9×512 (just over 4k)
    "5632b": 1,   # was 4097b → 11×512
    "6656b": 1,   # was 513b/1023b region stand-in → 13×512
    "7680b": 1,   # was 8191b → 15×512 (just under 8k)
    "8704b": 1,   # was 8193b → 17×512 (just over 8k)
    "9728b": 1,   # was 2047b region stand-in → 19×512
    "14848b": 1,  # was 16383b-ish lower → 29×512
    "15872b": 1,  # was 16383b → 31×512 (just under 16k)
}

assert sum(temp_dict.values()) == 100, sum(temp_dict.values())
assert temp_dict["4k"] == 19
assert "8m" not in temp_dict and "16m" not in temp_dict
assert "6145k" not in temp_dict and "7169k" not in temp_dict
assert "10241k" not in temp_dict and "12289k" not in temp_dict

# Boundary replacements must exist, be 512-aligned, and stay off pure 4KiB multiples
# (except we only require 512 alignment globally below).
_BOUNDARY = ("4608b", "5632b", "6656b", "7680b", "8704b", "9728b", "14848b", "15872b")
for label in _BOUNDARY:
    assert label in temp_dict and temp_dict[label] == 1
    assert _bs_bytes(label) % 512 == 0, label
    assert _bs_bytes(label) % 4096 != 0, label

# mix_512: every model block size must be 512-byte aligned.
for label in temp_dict:
    assert _bs_bytes(label) % 512 == 0, f"{label} not 512-aligned"

# Soft memory gate: no size above ~5.1MiB (5121k).
assert max(_bs_bytes(k) for k in temp_dict) <= 5121 * 1024

total = 1000
proportion_dict = {k: int(v * 0.01 * total) for k, v in temp_dict.items()}

random_p = {}
for k, v in proportion_dict.items():
    random_p_num_100 = v // 2
    random_p_num_0 = v - random_p_num_100
    random_p[k] = [100] * random_p_num_100
    random_p[k].extend([0] * random_p_num_0)
    random.shuffle(random_p[k])

read_p = {}
for k, v in proportion_dict.items():
    read_p_num_common = v // 6
    read_p_num_100 = v - 5 * read_p_num_common
    read_p[k] = [100] * read_p_num_100
    for vv in [0, 20, 40, 60, 80]:
        read_p[k].extend([vv] * read_p_num_common)
    random.shuffle(read_p[k])


def parse_dict(d):
    new_d = copy.deepcopy(d)
    for k, v in d.items():
        if v == 0:
            del new_d[k]
    return new_d


bs = []
for _i in range(total):
    proportion_dict = parse_dict(proportion_dict)
    random_key = random.choice(list(proportion_dict.keys()))
    bs.append(random_key)
    proportion_dict[random_key] -= 1

random.shuffle(bs)

with open("random_choice.csv", "w", encoding="utf-8", newline="\n") as fp:
    fp.write(
        "Block_Size,Random_Percentage,Read_Percentage,Queue_Depth,"
        "Run_Time(ss:mm:hh:dd),Number_of_Jobs,Offset\n"
    )
    for b in bs:
        random_p_v = random_p[b].pop()
        read_p_v = read_p[b].pop()
        fp.write(f"{b},{random_p_v},{read_p_v},32,30,8,0\n")
    fp.write("End\n")