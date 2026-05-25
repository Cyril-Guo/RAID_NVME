import random
import copy

temp_dict = {
    "512b": 4, "1k": 1, "1536b": 1, "2k": 1, "2560b": 1, "3k": 1,
    "3584b": 1, "4k": 63, "8k": 6, "16k": 5, "32k": 3, "64k": 3,
    "1m": 2, "2m": 2, "4m": 2, "8m": 2, "16m": 2
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
        fp.write(f"{b},{random_p_v},{read_p_v},32,30,1,0\n")
    fp.write("End\n")
