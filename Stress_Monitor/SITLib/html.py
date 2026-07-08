#!/usr/bin/python
# -*- coding: utf-8 -*-
# @Time: 2022/8/9
# @Author: SunChao
# @Project: YxLake_Expander_Monitor
import os
import re
import json
import shutil
from SITLib import constant
from SITLib.configure import threshold, item2name, delete_exception_items
from SITLib.utils import cmd, get_split_by_LF

color_list = ["#3888fa", "#3CB371", "#FF8C00", "#FF4500", "#FFD700", "#6A5ACD", "#FF1493", "#9932CC", "#BA55D3", "#ADFF2F"]

HTML_HEAD = r"""
<html lang="zh-cn">
<head>
    <meta charset="UTF-8">
    <link rel="stylesheet" type="text/css" href="bootstrap.min.css">
    <title>磁盘监控报告 (Disk Monitor Report)</title>
    <script src="echarts.min.js"></script>
    <script src="bootstrap.bundle.min.js"></script>
    <script src="element-resize-detector.min.js"></script>
    <style>
    main{
        display:flex;
        position: fixed;
        flex-wrap:nowrap;
        height:100vh;
        max-height:100vh;
        margin: 0;
        z-index: 1000;
        border:solid rgba(93, 126, 255, 0.35);
        border-width:1px 1px;
    }
    .scrollarea{overflow-y:auto}
     .d-flex{
         margin-top:10px;
         width: 100%;
     }
    .myChart{
        width: 100%;
        padding:2px 10px 0 10px;
        overflow-x:auto
    }    
    .contentArea{
        padding-left:180px;
        width:96%
    }
    .exceptionArea{
        padding-left:180px;
        width:96%;
        margin-bottom: 20px;
    }
    .myTable{
        width: 100%;
        text-align:center;
    }
    .exceptionTable th {
        background: #f8d7da;
        color: #721c24;
    }
    .exceptionTable td {
        background: #f8d7da;
        color: #721c24;
        font-weight: bold;
    }
    th {
        font: bold 11px "Trebuchet MS", Verdana, Arial, Helvetica, sans-serif;
        color: #4f6b72;
        border: 1px solid #C1DAD7;
        letter-spacing: 2px;
        text-align: center;
        padding: 6px;
        background: #CAE8EA;
    }
    td {
        border: 1px solid #C1DAD7;
        background: #fff;
        font-size:11px;
        padding: 6px;
        color: #4f6b72;
    }
    </style>
</head>
<body>
<main>
  <div class="flex-shrink-0 p-3 bg-light" style="width: 180px">
    <h5 class="pb-2 border-bottom">监控项目</h5>
    <ul class="list-unstyled ps-0">
      <li class="mb-1">
        <button class="btn btn-toggle align-items-center rounded collapsed" style="font-weight:600">磁盘监控</button>
      </li>
    </ul>
  </div>
</main>
"""

HTML_TAIL = r"""</body></html>"""

def gen_option_series(data):
    cnt = 0
    template_series = '['
    for k, v in data.items():
        if k == "Timestamp": continue
        color = color_list[cnt % len(color_list)]
        template_series += r"""{{
              name: "{}", itemStyle: {{ normal: {{ color: '{}' }} }},
              smooth: true, type: 'line', data: {},
              animationDuration: 1000
              }},
        """.format(k, color, v)
        cnt += 1
    template_series += ']'
    return template_series

def gen_exception_table(cats):
    exceptions = []
    # Identify fluctuations > 10% from average
    for (img_title, bar, valueList, _, _) in cats:
        # Only check performance metrics
        if img_title not in ['rkB/s', 'wkB/s', 'r/s', 'w/s']: continue
        
        timestamps = json.loads(bar)
        for device_id, vals in valueList.items():
            if not vals: continue
            valid_vals = [v for v in vals if isinstance(v, (int, float))]
            if not valid_vals: continue
            avg = sum(valid_vals) / len(valid_vals)
            if avg == 0: continue
            
            for i, val in enumerate(vals):
                if not isinstance(val, (int, float)): continue
                diff = abs(val - avg) / avg
                if diff > 0.1: # 10% threshold
                    exceptions.append({
                        'time': timestamps[i] if i < len(timestamps) else "Unknown",
                        'device': device_id,
                        'item': img_title,
                        'value': val,
                        'avg': round(avg, 2),
                        'diff': round(diff * 100, 2)
                    })
    
    if not exceptions:
        return ""
        
    div = r"""<div class="exceptionArea">
    <h3 style="color:red">性能异常记录 (Performance Exceptions > 10% Fluctuations)</h3>
    <table class="myTable exceptionTable">
    <tr><th>时间 (Timestamp)</th><th>设备 (Disk)</th><th>指标 (Metric)</th><th>数值 (Value)</th><th>周期均值 (Average)</th><th>波动幅度 (Fluctuation)</th></tr>"""
    for ex in exceptions:
        div += "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}%</td></tr>".format(
            ex['time'], ex['device'], ex['item'], ex['value'], ex['avg'], ex['diff'])
    div += "</table></div>"
    return div

def gen_div(cats):
    div = r""
    for (img_title, bar, valueList, _, _) in cats:
        format_id = "s" + re.sub(r'[\s\(\)%\+\./-]', '_', img_title)
        div += r"""<div style="width:100%">
        <div id="{}" style="width: 98%;height:300px;padding:10px"></div>
        {}
        </div>""".format(format_id, gen_table_series(valueList))
    return div

def gen_js(hlist):
    js = r"""<script type="text/javascript">"""
    for img_title, bar, legend, series in hlist:
        format_id = "s" + re.sub(r'[\s\(\)%\+\./-]', '_', img_title)
        js += r"""
        var {id}Bar = echarts.init(document.getElementById('{id}'));
        {id}Bar.setOption({{
            title: {{ text: "{title}", left: "center" }},
            tooltip: {{ trigger: 'axis' }},
            legend: {{ data: {legend}, top: 30 }},
            grid: {{ left: '3%', right: '4%', bottom: '15%', containLabel: true }},
            xAxis: {{ type: 'category', boundaryGap: false, data: {bar} }},
            yAxis: {{ type: 'value' }},
            dataZoom: [{{ type: 'slider', start: 0, end: 100 }}, {{ type: 'inside' }}],
            series: {series}
        }});
        """.format(id=format_id, title=img_title, bar=bar, legend=legend, series=series)
    js += r"""</script>"""
    return js

def gen_table_series(valueList):
    div = r"""<div class="myChart"><table class="myTable"><tr><th width="120px">Item</th>"""
    tdmin = "<tr><td>Min Value</td>"
    tdavg = "<tr><td>Avg Value</td>"
    tdmax = "<tr><td>Max Value</td>"
    for name, vals in valueList.items():
        if name.lower() == 'timestamp': continue
        valid_vals = [v for v in vals if isinstance(v, (int, float))]
        min_v = min(valid_vals) if valid_vals else "N/A"
        max_v = max(valid_vals) if valid_vals else "N/A"
        avg_v = round(sum(valid_vals)/len(valid_vals), 2) if valid_vals else "N/A"
        div += "<th>{}</th>".format(name)
        tdmin += "<td>{}</td>".format(min_v)
        tdavg += "<td>{}</td>".format(avg_v)
        tdmax += "<td>{}</td>".format(max_v)
    div += "</tr>" + tdmin + "</tr>" + tdavg + "</tr>" + tdmax + "</tr></table></div>"
    return div

class MixInHTML(object):
    @staticmethod
    def mixin(ori_dict, idx, mode, interval, test_item):
        hlist = []
        body_content = ""
        exception_content = ""
        all_chart_data = [] # Combined for exception tracking
        
        # System resource keys and Disk performance keys (Reordered per user request)
        resource_mapping = {
            "DISK_IO": "Disk Performance (Throughput)",
            "DISK_IOPS": "Disk Performance (IOPS)",
            "SYSTEM_CPU": "System CPU Usage",
            "SYSTEM_MEM": "System Memory Usage",
            "DISK_UTIL": "Disk Performance (Utility)"
        }
        
        for key, title in resource_mapping.items():
            if key in ori_dict and ori_dict[key]:
                data_list = ori_dict[key]
                chart_data = []
                for entry in data_list:
                    ts = entry.get('Timestamp', [])
                    for img_title, values in entry.items():
                        if img_title.lower() == 'timestamp' or not values: continue
                        legend = json.dumps(list(values.keys()))
                        series = gen_option_series(values)
                        chart_data.append((img_title, json.dumps(ts), values, legend, series))
                        hlist.append((img_title, json.dumps(ts), legend, series))
                
                all_chart_data.extend(chart_data)
                div_content = gen_div(chart_data)
                body_content += r"""<div class="contentArea"><h3 class="importHeader">[{}]</h3>{}</div>""".format(title, div_content)

        # Prepend Performance Exceptions at the top
        exception_html = gen_exception_table(all_chart_data)
        
        html_content = HTML_HEAD + exception_html + body_content + gen_js(hlist) + HTML_TAIL
        if idx == 1:
            fpath = os.path.join(constant.LOGAD, "result.html")
        else:
            fpath = os.path.join(constant.LOGAD, "result_{}.html".format(idx - 1))
            
        with open(fpath, 'w', encoding='utf-8') as f:
            f.write(html_content)
