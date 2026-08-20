import random
import copy

# Old mix model (4k-heavy). Kept for reference.
# temp_dict = {
#     "512b": 4, "1k": 1, "1536b": 1, "2k": 1, "2560b": 1, "3k": 1,
#     "3584b": 1, "4k": 63, "8k": 6, "16k": 5, "32k": 3, "64k": 3,
#     "1m": 2, "2m": 2, "4m": 2, "8m": 2, "16m": 2
# }

# New mix model: reduce 4k from 63 -> 23, redistribute 40 to more block sizes
# for broader coverage (non-power-of-2 / mid-range sizes).
temp_dict = {
    "512b": 4, "1k": 1, "1536b": 1, "2k": 1, "2560b": 1, "3k": 1,
    "3584b": 1, "4k": 23, "8k": 6, "16k": 5, "32k": 3, "64k": 3,
    "1m": 2, "2m": 2, "4m": 2, "8m": 2, "16m": 2,
    # +40 weight across 40 extra block sizes (1 each)
    "5k": 1, "6k": 1, "7k": 1, "9k": 1, "10k": 1, "11k": 1, "12k": 1,
    "13k": 1, "14k": 1, "15k": 1, "17k": 1, "18k": 1, "20k": 1, "24k": 1,
    "28k": 1, "36k": 1, "40k": 1, "48k": 1, "56k": 1, "72k": 1, "80k": 1,
    "96k": 1, "112k": 1, "128k": 1, "160k": 1, "192k": 1, "224k": 1,
    "256k": 1, "320k": 1, "384k": 1, "448k": 1, "512k": 1, "768k": 1,
    "896k": 1, "3m": 1, "5m": 1, "6m": 1, "7m": 1, "10m": 1, "12m": 1,
}

proportion_dict = {k: int(v * 0.01 * 1400) for k, v in temp_dict.items()}

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
total = 1400

for i in range(total):
    proportion_dict = parse_dict(proportion_dict)
    random_key = random.choice(list(proportion_dict.keys()))
    bs.append(random_key)
    proportion_dict[random_key] -= 1

random.shuffle(bs)

with open("random_choice.csv", "w") as fp:
    fp.write("Block_Size,Random_Percentage,Read_Percentage,Queue_Depth,Run_Time(ss:mm:hh:dd),Number_of_Jobs,Offset\n")
    for b in bs:
        random_p_v = random_p[b].pop()
        read_p_v = read_p[b].pop()
        fp.write(f"{b},{random_p_v},{read_p_v},32,30,12,0\n")
    fp.write("End\n")
