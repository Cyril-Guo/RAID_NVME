#!/usr/bin/python
# -*- coding: utf-8 -*-
# @Time: 2022/8/9
# @Author: SunChao 
# @Project: YxLake_Expander_Monitor

import os
import sys
import time
import signal
import shutil
import glob
from threading import Timer
from SITLib.utils import cmd, show_fail_message, get_split_by_LF, show_produce_message, isFloatNum, process_col_val
from SITLib import constant
from SITLib.arguments import parse_args
from SITLib.html import MixInHTML

def get_log_col_value_list(fpath, segment, is_filter=True):
    if not os.path.exists(fpath):
        return [], []
    lines = open(fpath).readlines()
    if not lines:
        return [], []
    log_col_names = [k.replace('+', '') for k in lines[0].strip().split(',')]
    log_col_value_list = [[] for i in log_col_names]
    
    for idx, line in enumerate(lines):
        if idx == 0: continue
        parts = line.strip().split(',')
        if not parts: continue
        
        try:
            ts_str = parts[0]
            ts = time.mktime(time.strptime(ts_str, "%Y-%m-%d %H:%M:%S"))
            if is_filter:
                if ts < segment[0]: continue
                if ts > segment[1]: break
            
            # Timestamp passed or no filter needed
            for col_idx, col_val in enumerate(parts):
                if col_idx < len(log_col_names):
                    if col_idx == 0:
                        log_col_value_list[col_idx].append(col_val)
                    else:
                        log_col_value_list[col_idx].append(process_col_val(col_val))
        except:
            continue
            
    return log_col_names, log_col_value_list

def process_result_vatal(res_dict, segment, echart_div_id="DISK", img_title="io"):
    echart_data = {}
    dir_path = os.path.join(constant.LOGAD, echart_div_id)
    if not os.path.exists(dir_path): return res_dict

    cfg_path = os.path.join(dir_path, '{}.cfg'.format(img_title.replace('ps', '')))
    if os.path.exists(cfg_path):
        with open(cfg_path) as f:
            for line in f.readlines():
                device_id = line.strip()
                log_path = os.path.join(dir_path, '{}_{}.log'.format(device_id, img_title))
                if os.path.exists(log_path):
                    with open(log_path) as fout:
                        header = fout.readline()
                        if header:
                            log_col_names = [k for k in header.strip().split(',')]
                            echart_data = {col_name: {} for col_name in log_col_names if col_name.lower() != 'timestamp'}
                    break
        with open(cfg_path) as f:
            for line in f.readlines():
                device_id = line.strip()
                fpath = os.path.join(dir_path, '{}_{}.log'.format(device_id, img_title))
                if os.path.exists(fpath):
                    log_col_names, log_col_value_list = get_log_col_value_list(fpath, segment)
                    for col_name, col_value_list in zip(log_col_names, log_col_value_list):
                        if col_name.lower() == 'timestamp':
                            if 'Timestamp' not in echart_data:
                                echart_data['Timestamp'] = col_value_list
                        elif col_name in echart_data:
                            echart_data[col_name][device_id] = col_value_list

    res_dict["{}_{}".format(echart_div_id, img_title.upper())].append(echart_data)
    return res_dict

def get_segment_timestamp(seg_time=3600):
    segments = []
    # Use actual start time from this monitoring run
    st_file = os.path.join(constant.LOGAD, 'DISK', 'start_time.log')
    start_time = -1
    if os.path.exists(st_file):
        try:
            with open(st_file) as f:
                start_time = float(f.read().strip())
        except: pass
    
    # If not found (e.g., generate-only), look for the oldest log
    if start_time == -1:
        for root, _, files in os.walk(constant.LOGAD):
            for file in files:
                if file.endswith(".log") and file != "iostat_runtime.log":
                    fpath = os.path.join(root, file)
                    try:
                        with open(fpath) as f:
                            f.readline() # Header
                            line = f.readline()
                            if line:
                                ts_str = line.split(',')[0]
                                st = time.mktime(time.strptime(ts_str, "%Y-%m-%d %H:%M:%S"))
                                if start_time == -1 or st < start_time:
                                    start_time = st
                    except: continue
            if start_time != -1: break

    curr_now = time.time()
    if start_time == -1:
        start_time = curr_now - 600 # Default to 10 mins ago
    
    end_time = curr_now + 60 # Buffer
    duration = end_time - start_time
    
    # Only segment if duration exceeds seg_time
    if duration <= seg_time:
        x = 0
    else:
        x = int(duration // seg_time)
    
    for i in range(x + 1):
        s = start_time + i * seg_time
        e = s + seg_time
        segments.append([s, e])
    return segments

def show_html(mode, interval, test_item, segment_time):
    global gflag
    gflag = 1
    cmd(r'''rm -rf {}/*'''.format(os.path.join(constant.LOGAD, "ExceptionLog")))
    segments = get_segment_timestamp(seg_time=segment_time)
    if not segments:
        print("Warning: No monitoring segments found. Using default segment.")
        now = time.time()
        segments = [[now - 86400, now + 86400]]
    print("Segments Found: {}. Generating HTML reports...".format(len(segments)))
    
    for result_idx, segment in enumerate(segments):
        # Apply 2-min buffer: skip first 120s and last 120s of the segment
        buffered_segment = [segment[0] + 120, segment[1] - 120]
        if buffered_segment[0] >= buffered_segment[1]:
            # If segment is too short for buffer, fallback to original but skip first/last points
            buffered_segment = segment
            
        ori_dict = {"DISK_IO": [], "DISK_IOPS": [], "SYSTEM_CPU": [], "SYSTEM_MEM": [], "DISK_UTIL": []}

        # Order of calls determines order in HTML
        process_result_vatal(ori_dict, buffered_segment, echart_div_id="DISK", img_title="io")
        process_result_vatal(ori_dict, buffered_segment, echart_div_id="DISK", img_title="iops")
        process_result_vatal(ori_dict, buffered_segment, echart_div_id="SYSTEM", img_title="cpu")
        process_result_vatal(ori_dict, buffered_segment, echart_div_id="SYSTEM", img_title="mem")
        process_result_vatal(ori_dict, buffered_segment, echart_div_id="DISK", img_title="util")

        MixInHTML.mixin(ori_dict, result_idx + 1, mode, interval, test_item)

    # Sync logs to backup
    cmd(r'''cp -rf {} {}'''.format(constant.LOGAD, os.path.abspath(os.path.join(constant.CUR_DIR, '../log'))))

class StressMonitor(object):
    def __init__(self, runtime, mode='fio', interval=1, bmcip=None):
        self.runtime = int(runtime)
        self.endtime = time.time() + self.runtime
        self.bmcip = bmcip if bmcip else ""
        self.interval = interval
        self.mode = "fio"
        self.start_monitor_time = time.time()
        self.redhat7, _ = cmd(r'''less /etc/redhat-release |grep -i 'release 7' |wc -l''')
        self.redhat9, _ = cmd(r'''less /etc/redhat-release |grep -i 'release 9' |wc -l''')

    def prepare_log(self):
        # Cross-platform cleanup using native python calls
        sub_log_dir = os.path.join(constant.LOGAD, self.bmcip)
        if os.path.exists(sub_log_dir):
            shutil.rmtree(sub_log_dir, ignore_errors=True)
            
        os.makedirs(os.path.join(sub_log_dir, "DISK"), exist_ok=True)
        os.makedirs(os.path.join(sub_log_dir, "SYSTEM"), exist_ok=True)
        os.makedirs(os.path.join(sub_log_dir, "ExceptionLog"), exist_ok=True)
        
        # Explicitly cleanup all old reports across all platforms
        old_reports = glob.glob(os.path.join(constant.LOGAD, "result*.html"))
        for report in old_reports:
            try:
                os.remove(report)
            except: pass

        for tool_file in ["echarts.min.js", "bootstrap.bundle.min.js", "bootstrap.min.css", "element-resize-detector.min.js"]:
            src = os.path.join(constant.TOOL_DIR, tool_file)
            if os.path.exists(src):
                shutil.copy(src, sub_log_dir)

    def prepare_disk(self):
        show_produce_message("prepare disk")
        def get_system_disk_root():
            # Use more accurate way to get the parent disk of the root partition
            stdout, _ = cmd(r'''lsblk -no pkname /''')
            if not stdout: # fallback
                stdout, _ = cmd(r'''lsblk | awk '$7 == "/" {print $1}' | sed 's/[^a-zA-Z]//g' ''')
            return stdout.strip() if stdout else ""

        self.system_disk = get_system_disk_root()
        disk_raw, _ = cmd(r'''iostat -x 1 1 | sed -n '7,$p' |awk {'print $1'}|grep -E -v '^dm' ''')
        # Robust exclusion: system disk (with partitions) and loop devices
        all_disks = [d for d in get_split_by_LF(disk_raw) if d]
        self.disk = []
        for d in all_disks:
            if d.startswith('loop'): continue
            if self.system_disk and d.startswith(self.system_disk): continue
            self.disk.append(d)
        
        print("System disk identified: {}, Target disks for monitor: {}".format(self.system_disk, self.disk))
        
        with open(os.path.join(constant.LOGAD, 'DISK', 'io.cfg'), 'w') as f:
            for d in self.disk: f.write('{}\n'.format(d))
        with open(os.path.join(constant.LOGAD, 'DISK', 'iops.cfg'), 'w') as f:
            for d in self.disk: f.write('{}\n'.format(d))
        with open(os.path.join(constant.LOGAD, 'DISK', 'util.cfg'), 'w') as f:
            for d in self.disk: f.write('{}\n'.format(d))
        # Start iostat background process
        iostat_cmd = r'''iostat -x {} >> {} &'''.format(self.interval, os.path.join(constant.LOGAD, "DISK", "iostat_runtime.log"))
        os.system(iostat_cmd)

    def prepare_system_stats(self):
        show_produce_message("prepare system stats")
        for ext, header in [('cpu', "Timestamp,CPU_Usage%"), ('mem', "Timestamp,Mem_Usage%")]:
            with open(os.path.join(constant.LOGAD, 'SYSTEM', 'usage_{}.log'.format(ext)), 'w') as f:
                f.write("{}\n".format(header))
            with open(os.path.join(constant.LOGAD, 'SYSTEM', '{}.cfg'.format(ext)), 'w') as f:
                f.write("usage\n")

    def get_system_usage(self):
        now_ts = time.time()
        now_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now_ts))
        
        # CPU Usage (Dual-language support for id/空闲)
        cpu_idle, _ = cmd(r'''top -b -n 1 | grep "Cpu(s)" | sed 's/%,/ /g' | awk -F'(id|空闲)' '{print $1}' | awk '{print $NF}' | grep -oE '[0-9.]+' ''')
        if not cpu_idle: cpu_idle = "100"
        try:
            cpu_usage = round(100.0 - float(cpu_idle), 2)
        except:
            cpu_usage = 0.0
            
        with open(os.path.join(constant.LOGAD, 'SYSTEM', 'usage_cpu.log'), 'a') as f:
            f.write("{},{}\n".format(now_str, cpu_usage))
            
        # Memory Usage (Dual-language support for Mem/内存)
        # Using (Total - Available) / Total for precision
        mem_info, _ = cmd(r'''free | grep -E '(Mem|内存)' | awk '{if ($2 > 0) print ($2-$NF)/$2 * 100; else print 0}' ''')
        if not mem_info or mem_info == "0":
            # Fallback for some systems where available is not the last column
            mem_info, _ = cmd(r'''free | grep -E '(Mem|内存)' | awk '{if ($2 > 0) print ($2-$7)/$2 * 100; else print 0}' ''')
            
        if not mem_info: mem_info = "0"
        try:
            mem_pct = round(float(mem_info), 2)
        except:
            mem_pct = 0.0
            
        with open(os.path.join(constant.LOGAD, 'SYSTEM', 'usage_mem.log'), 'a') as f:
            f.write("{},{}\n".format(now_str, mem_pct))

    def prepare_disk_io(self):
        show_produce_message("prepare disk io")
        for d in self.disk:
            with open(os.path.join(constant.LOGAD, 'DISK', '{}_io.log'.format(d)), 'w') as f:
                f.write("Timestamp,rkB/s,wkB/s\n")
            with open(os.path.join(constant.LOGAD, 'DISK', '{}_iops.log'.format(d)), 'w') as f:
                f.write("Timestamp,r/s,w/s\n")
            with open(os.path.join(constant.LOGAD, 'DISK', '{}_util.log'.format(d)), 'w') as f:
                f.write("Timestamp,util%\n")

    def get_disk_io(self):
        disk_cfg = os.path.join(constant.LOGAD, 'DISK', 'io.cfg')
        if not os.path.exists(disk_cfg): return
        with open(disk_cfg) as f:
            disk = get_split_by_LF(f.read())
        
        runtime_log = os.path.join(constant.LOGAD, 'DISK', 'iostat_runtime.log')
        if not os.path.exists(runtime_log): return

        # Extract samples for each disk
        for d in disk:
            io_tmp = os.path.join(constant.LOGAD, 'DISK', '{}_io.tmp'.format(d))
            iops_tmp = os.path.join(constant.LOGAD, 'DISK', '{}_iops.tmp'.format(d))
            util_tmp = os.path.join(constant.LOGAD, 'DISK', '{}_util.tmp'.format(d))
            # Use robust awk matching to handle leading spaces in iostat output
            pattern = r''' '$1=="{}"' '''.format(d)
            if self.redhat7 != '0':
                cmd(r'''awk {} '{}' | awk '{{print $6,$7}}' > {} '''.format(pattern, runtime_log, io_tmp))
                cmd(r'''awk {} '{}' | awk '{{print $4,$5}}' > {} '''.format(pattern, runtime_log, iops_tmp))
                cmd(r'''awk {} '{}' | awk '{{print $NF}}' > {} '''.format(pattern, runtime_log, util_tmp))
            elif self.redhat9 != '0':
                cmd(r'''awk {} '{}' | awk '{{print $3,$9}}' > {} '''.format(pattern, runtime_log, io_tmp))
                cmd(r'''awk {} '{}' | awk '{{print $2,$8}}' > {} '''.format(pattern, runtime_log, iops_tmp))
                cmd(r'''awk {} '{}' | awk '{{print $NF}}' > {} '''.format(pattern, runtime_log, util_tmp))
            else:
                cmd(r'''awk {} '{}' | awk '{{print $3,$9}}' > {} '''.format(pattern, runtime_log, io_tmp))
                cmd(r'''awk {} '{}' | awk '{{print $2,$8}}' > {} '''.format(pattern, runtime_log, iops_tmp))
                cmd(r'''awk {} '{}' | awk '{{print $NF}}' > {} '''.format(pattern, runtime_log, util_tmp))

        # Reconstruct CSV with timestamps
        for d in disk:
            for ext in ['io', 'iops', 'util']:
                tmp_f = os.path.join(constant.LOGAD, 'DISK', '{}_{}.tmp'.format(d, ext))
                if os.path.exists(tmp_f):
                    with open(os.path.join(constant.LOGAD, 'DISK', '{}_{}.log'.format(d, ext)), 'a') as f:
                        with open(tmp_f) as ft:
                            for idx, line in enumerate(ft.readlines()):
                                out = line.strip().split()
                                if not out: continue
                                # Use start_monitor_time as base (aligned offset)
                                ts_val = self.start_monitor_time + idx * self.interval
                                ts_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts_val))
                                f.write("{},{}\n".format(ts_str, ','.join(out)))
        cmd(r'''rm -rf {}/*.tmp'''.format(os.path.join(constant.LOGAD, 'DISK')))

    def recursive_monitor(self, end_time):
        global gflag
        if time.time() < end_time and gflag == 0:
            self.get_system_usage()
            Timer(self.interval, self.recursive_monitor, args=[end_time]).start()
        else:
            show_produce_message("Stopping iostat background monitor")
            cmd(r'''ps -ef | grep -i 'iostat -x' | grep -v grep | awk '{print $2}' | xargs kill -9 2>/dev/null ''')

    def monitor(self):
        show_produce_message("Starting monitor")
        self.start_monitor_time = time.time()
        # Persist start time for synchronization across instances
        with open(os.path.join(constant.LOGAD, 'DISK', 'start_time.log'), 'w') as f:
            f.write("{}".format(self.start_monitor_time))
        self.endtime = self.start_monitor_time + self.runtime
        
        with open(os.path.join(constant.LOGAD, 'runtime.ini'), 'w') as f:
            f.write("{}".format(self.runtime // 3600))
        
        # Start recursive system stats collector
        self.recursive_monitor(self.endtime)
        
        while time.time() <= self.endtime and gflag == 0:
            remaining = int(self.endtime - time.time())
            if remaining > 0:
                if remaining % 60 == 0 or remaining <= 10:
                    print("Monitoring... {}s remaining".format(remaining))
            time.sleep(1)
            
        show_produce_message('Monitoring complete')
        cmd(r'''rm -rf tmp*.log tmp.txt''')

    def install_system_tool(self):
        show_produce_message("install system tool")
        for tool, check_cmd in [("nvme-cli", "nvme --help"), ("smartmontools", "smartctl --help")]:
            _, ret = cmd(check_cmd)
            if ret != 0:
                cmd(r'''yum -y install {} 2>/dev/null'''.format(tool))
                cmd(r'''apt-get -y install {} 2>/dev/null'''.format(tool))
                _, ret = cmd(check_cmd)
                if ret != 0:
                    show_fail_message("Please install {} !!!".format(tool))
                    sys.exit(1)

    def start(self):
        self.install_system_tool()
        self.prepare_log()
        self.prepare_system_stats()
        self.prepare_disk()
        self.prepare_disk_io()
        self.monitor()

def handler(sig, frame):
    global gflag
    gflag = 1

if __name__ == '__main__':
    args = parse_args()
    gflag = 0
    signal.signal(signal.SIGTERM, handler)
    signal.signal(signal.SIGINT, handler)
    
    if sys.version_info[0] < 3:
        show_fail_message("Please use Python 3+")
        sys.exit(1)

    try:
        sm = StressMonitor(runtime=args.RUNTIME, mode='fio', interval=args.INTERVAL)
        if not args.GENERATEONLY:
            sm.prepare_log()
            sm.start()
    except Exception as e:
        gflag = 1
        print('Error during monitor:', e)
    finally:
        # Final cleanup and report generation
        cmd(r'''ps -ef | grep -i 'iostat -x' | grep -v grep | awk '{print $2}' | xargs kill -9 2>/dev/null ''')
        # Re-initialize for report generation to ensure all final logs are processed
        report_sm = StressMonitor(runtime=args.RUNTIME, mode='fio', interval=args.INTERVAL)
        # We need the start time from the actual run, let's try to get it from start_time.log if it exists
        st_file = os.path.join(constant.LOGAD, 'DISK', 'start_time.log')
        if os.path.exists(st_file):
            with open(st_file) as f:
                try: report_sm.start_monitor_time = float(f.read().strip())
                except: pass
        
        report_sm.get_disk_io()
        show_html('fio', args.INTERVAL, 'fio', args.SEGMENTTIME)
        print("Report generated successfully. Results in {}/result.html".format(constant.LOGAD))
        print("Done.")
