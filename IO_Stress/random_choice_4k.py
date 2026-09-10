#!/usr/bin/env python3
"""Mix IO block-size model (4k).

Primary: 4k weight 10 (10%).
Others: 90 distinct 4k-aligned sizes weight 1 each (90%), spanning 8k..16m
with explicit low / mid / high bands (not clustered below ~600k).
Weights sum to 100. Generates MixIO CSV with total=3500 rows.
"""
from __future__ import annotations

import copy
import random

temp_dict = {
    "4k": 10,
    "8k": 1, "12k": 1, "16k": 1, "20k": 1, "24k": 1, "28k": 1, "32k": 1, "36k": 1,
    "40k": 1, "44k": 1, "48k": 1, "52k": 1, "56k": 1, "60k": 1, "64k": 1, "68k": 1,
    "72k": 1, "76k": 1, "80k": 1, "84k": 1, "88k": 1, "96k": 1, "112k": 1, "128k": 1,
    "144k": 1, "160k": 1, "176k": 1, "192k": 1, "208k": 1, "224k": 1, "240k": 1,
    "256k": 1, "272k": 1, "288k": 1, "304k": 1, "320k": 1, "336k": 1, "352k": 1,
    "368k": 1, "384k": 1, "400k": 1, "416k": 1, "432k": 1, "448k": 1, "464k": 1,
    "480k": 1, "496k": 1, "512k": 1, "528k": 1, "544k": 1, "560k": 1, "576k": 1,
    "592k": 1, "608k": 1, "624k": 1, "640k": 1, "656k": 1, "672k": 1, "688k": 1,
    "704k": 1, "720k": 1, "736k": 1, "752k": 1, "768k": 1, "896k": 1, "1m": 1,
    "1152k": 1, "1280k": 1, "1408k": 1, "1536k": 1, "1664k": 1, "1792k": 1, "1920k": 1,
    "2m": 1, "2560k": 1, "3m": 1, "3584k": 1, "4m": 1, "5m": 1, "6m": 1, "7m": 1,
    "8m": 1, "9m": 1, "10m": 1, "11m": 1, "12m": 1, "13m": 1, "14m": 1, "15m": 1,
    "16m": 1
}

assert sum(temp_dict.values()) == 100, sum(temp_dict.values())
assert temp_dict["4k"] == 10
assert len(temp_dict) == 91
assert "16m" in temp_dict

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
