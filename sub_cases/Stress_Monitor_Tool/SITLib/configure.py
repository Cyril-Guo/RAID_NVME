#!/usr/bin/python
# -*- coding: utf-8 -*-


item2name = {"rkB/s": "DISK_IO", "wkB/s": "DISK_IO", "util%": "DISK_IO"}

threshold = {
    'disk_io': (-0.1, 0.1),
}

#不绘画异常点的log项
delete_exception_items = ["util"]

MODE = ['fio']
