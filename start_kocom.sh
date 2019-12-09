#!/bin/sh
mkdir logs 2>/dev/null
nohup python3 -u kocom.py > logs/kocom.log 2>&1 & sleep 1 ; tail -100f logs/kocom.log
