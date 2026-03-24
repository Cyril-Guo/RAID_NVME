#!/usr/bin/python
# -*- coding = utf-8 -*-
import argparse

def parse_args():
    usage = "Disk Performance Monitor Tool\n" \
            "Example: python3 main.py -r 43200 -i 1\n"

    parser = argparse.ArgumentParser(description="Disk Performance Monitor Parameters", usage=usage)
    parser.add_argument('-r', type=int, dest='RUNTIME', default=43200, help="Runtime in seconds (default: 43200)")
    parser.add_argument('-i', type=int, dest='INTERVAL', default=1, help="Monitor interval in seconds (default: 1)")
    parser.add_argument('-g', dest='GENERATEONLY', action='store_true', help="Generate HTML report from existing logs only")
    parser.add_argument('-s', type=int, dest='SEGMENTTIME', default=43200, help="Segment duration for splitting result.html")
    
    return parser.parse_args()
