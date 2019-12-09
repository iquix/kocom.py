#!/bin/sh
ps ax | grep kocom.py | grep -v grep | awk '{print "kill " $1}'|sh
