#!/usr/bin/env python3
"""Mix IO block-size model (4k) — memory-capped.

Peak fio buffer memory (all 4 MixIO streams at max bs simultaneously):
  mem ≈ 4 * disks * numjobs(12) * iodepth(32) * bs

With disks=20 and bs_max=4m → ≈120 GiB (budget ≤170 GiB on a 200 GiB host).
Larger than 4m is excluded. Pool favors 4k / small-mid sizes; few large sizes.
Weights sum to 100. Generates MixIO CSV with total=3500 rows.
"""
from __future__ import annotations

import copy
import random

# Cap: 4m. Do not add 5m..16m — those push 20-disk peak above ~150 GiB.
temp_dict = {
    # primary
    "4k": 20,
    # small 4k-aligned
    "8k": 6,
    "12k": 3,
    "16k": 5,
    "20k": 2,
    "24k": 2,
    "28k": 1,
    "32k": 5,
    "36k": 1,
    "40k": 1,
    "48k": 3,
    "56k": 1,
    "64k": 5,
    "80k": 1,
    "96k": 2,
    # mid
    "112k": 1,
    "128k": 4,
    "160k": 1,
    "192k": 2,
    "224k": 1,
    "256k": 4,
    "320k": 1,
    "384k": 2,
    "448k": 1,
    "512k": 4,
    "640k": 1,
    "768k": 2,
    "896k": 1,
    # large but ≤4m (sparse)
    "1m": 4,
    "1280k": 1,
    "1536k": 2,
    "1792k": 1,
    "2m": 3,
    "2560k": 1,
    "3m": 2,
    "3584k": 1,
    "4m": 2,
}

assert sum(temp_dict.values()) == 100, sum(temp_dict.values())
assert temp_dict["4k"] == 20
assert "4m" in temp_dict
assert "5m" not in temp_dict and "8m" not in temp_dict and "16m" not in temp_dict
assert max(
    (
        (int(k[:-1]) * 1024 if k.endswith("k") else int(k[:-1]) * 1024 * 1024)
        if k[-1] in "km"
        else int(k)
    )
    for k in temp_dict
) == 4 * 1024 * 1024

total = 3500
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
    for k, v in list(d.items()):
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
        fp.write(f"{b},{random_p_v},{read_p_v},32,30,12,0\n")
    fp.write("End\n")