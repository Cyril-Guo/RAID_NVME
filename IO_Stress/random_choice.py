import random
import copy

# Old mix model (4k-heavy). Kept for reference.
# temp_dict = {
#     "512b": 4, "1k": 1, "1536b": 1, "2k": 1, "2560b": 1, "3k": 1,
#     "3584b": 1, "4k": 63, "8k": 6, "16k": 5, "32k": 3, "64k": 3,
#     "1m": 2, "2m": 2, "4m": 2, "8m": 2, "16m": 2
# }

# Previous mix model: reduce 4k from 63 -> 23, redistribute 40 to more block sizes
# for broader coverage (non-power-of-2 / mid-range sizes).
temp_dict = {
    "512b": 4, "1k": 1, "1536b": 4, "2k": 1, "2560b": 1, "3k": 2,
    "3584b": 1, "4k": 19, "8k": 6, "16k": 5, "32k": 3, "64k": 3,
    "1m": 2, "2m": 2, "4m": 2, "8m": 2, "16m": 2,
    # +40 weight across 40 extra block sizes (1 each, all non-4k-aligned after 20k)
    "5k": 1, "6k": 1, "7k": 1, "9k": 1, "10k": 1, "11k": 1, "12k": 1,
    "13k": 1, "14k": 1, "15k": 1, "17k": 1, "18k": 1, "20k": 1, "25k": 1,
    "29k": 1, "37k": 1, "41k": 1, "49k": 1, "57k": 1, "73k": 1, "81k": 1,
    "97k": 1, "113k": 1, "129k": 1, "161k": 1, "193k": 1, "225k": 1,
    "257k": 1, "321k": 1, "385k": 1, "449k": 1, "513k": 1, "769k": 1,
    "897k": 1, "3073k": 1, "5121k": 1, "6145k": 1, "7169k": 1, "10241k": 1, "12289k": 1,
}

# Mix model: 512/10:1k/8:2k/8:4k/15:8k/12:16k/12:32k/10:64k/10:128k/8:256k/4:512k/2:1m/1
# temp_dict = {
#     "512b": 10, "1k": 8, "2k": 8, "4k": 15, "8k": 12, "16k": 12,
#     "32k": 10, "64k": 10, "128k": 8, "256k": 4, "512k": 2, "1m": 1,
# }

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
