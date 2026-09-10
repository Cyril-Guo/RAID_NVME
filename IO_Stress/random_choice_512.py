#!/usr/bin/env python3
"""Mix IO block-size model (512).

Primary: 512b weight 10 (10%).
Others: 90 distinct 512-aligned sizes weight 1 each (90%).
Weights sum to 100. Generates MixIO CSV with total=3500 rows.
"""
from __future__ import annotations

import copy
import random

temp_dict = {
    "512b": 10,
    "1k": 1, "1536b": 1, "2k": 1, "2560b": 1, "3k": 1, "3584b": 1, "4608b": 1, "5k": 1,
    "5632b": 1, "6k": 1, "6656b": 1, "7k": 1, "7680b": 1, "8704b": 1, "9k": 1,
    "9728b": 1, "10k": 1, "10752b": 1, "11k": 1, "11776b": 1, "12800b": 1, "13k": 1,
    "13824b": 1, "14k": 1, "14848b": 1, "15k": 1, "15872b": 1, "16896b": 1, "17k": 1,
    "17920b": 1, "18k": 1, "18944b": 1, "19k": 1, "19968b": 1, "20992b": 1, "21k": 1,
    "22016b": 1, "22k": 1, "23040b": 1, "23k": 1, "24064b": 1, "25088b": 1, "25k": 1,
    "26112b": 1, "26k": 1, "27136b": 1, "27k": 1, "28160b": 1, "29184b": 1, "29k": 1,
    "30208b": 1, "30k": 1, "31232b": 1, "31k": 1, "32256b": 1, "33280b": 1, "33k": 1,
    "34304b": 1, "34k": 1, "35328b": 1, "35k": 1, "36352b": 1, "37376b": 1, "37k": 1,
    "38400b": 1, "38k": 1, "39424b": 1, "39k": 1, "40448b": 1, "41472b": 1, "41k": 1,
    "42496b": 1, "42k": 1, "43520b": 1, "43k": 1, "44544b": 1, "45568b": 1, "45k": 1,
    "46592b": 1, "46k": 1, "47616b": 1, "47k": 1, "48640b": 1, "49664b": 1, "49k": 1,
    "50688b": 1, "50k": 1, "51712b": 1, "51k": 1, "52736b": 1
}

assert sum(temp_dict.values()) == 100, sum(temp_dict.values())
assert temp_dict["512b"] == 10
assert len(temp_dict) == 91

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
        fp.write(f"{b},{random_p_v},{read_p_v},32,30,12,0\n")
    fp.write("End\n")
