#!/usr/bin/python
# -*- coding: utf-8 -*-
import os
import sys
import subprocess
import signal
from SITLib import constant

RED = '\033[1;31m'
GREEN = '\033[1;32m'
ORANGE = '\033[1;33m'
END_COLOR = '\033[0m'

def get_split_by_LF(text):
    return [i.strip() for i in text.split('\n') if i.strip() ]

def show_produce_message(text):
    text_length = len(text)
    title_length = 80 - text_length
    half = title_length // 2
    str_ = '-' * half
    text = GREEN + str_ + text + str_ + END_COLOR
    print(text)
    return text

def show_fail_message(text):
    text = RED + text + END_COLOR
    print(text)
    return text

def show_title(text):
    text = ORANGE + "[" + text + "]" + END_COLOR
    print(text)
    return text

def cmd(shell, cwd=constant.CUR_DIR, print_=False):
    stdout, stderr, retcode = '', '', -1
    try:
        sys_result = subprocess.Popen(shell, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd)
        outdata, errdata = sys_result.communicate()
        retcode = sys_result.returncode
        stdout = outdata.decode('utf-8').strip()
        stderr = errdata.decode('utf-8').strip()
    except Exception as e:
        print(e)
    finally:
        if print_:
            print(stdout)
    return stdout, retcode

def isFloatNum(s):
    try:
        float(str(s).strip())
        return True
    except:
        return False

def process_col_val(col_val):
    if isFloatNum(col_val):
        ret_val = round(float(col_val), 2)
    elif col_val.find('yes') != -1:
        ret_val = 1
    elif col_val.find('no') != -1:
        ret_val = "no reading"
    elif col_val.find('--') != -1:
        ret_val = "no reading"
    else:
        ret_val = -1
    return ret_val

def get_all_disks():
    sys_disk, _ = cmd(r'''fdisk -l 2>/dev/null | grep dev | grep Disk | grep -v "mapper\|nvme" | sort | sed 's/.*\(\/dev\/.*\):.*/\1/' | sed 's/\/dev\/\(.*\)/\1/' ''')
    if sys_disk.find('Disk') != -1:
        sys_disk, _ = cmd(r'''fdisk -l 2>/dev/null|grep dev|grep Disk|grep -v "mapper\|nvme"|sort | sed 's/.*\(\/dev\/.*\)：.*/\1/' | sed 's/\/dev\/\(.*\)/\1/' ''')
    sys_disk = get_split_by_LF(sys_disk)
    return sys_disk

if __name__ == '__main__':
    pass
