#!/bin/bash
# Script to kill all running Alpaca websocket connections

echo "Checking for running Python websocket processes..."

# Find and kill all test.py processes
pids=$(ps aux | grep -i "python.*test.py" | grep -v grep | awk '{print $2}')

if [ -z "$pids" ]; then
    echo "No running websocket processes found."
else
    echo "Found processes: $pids"
    echo "Killing processes..."
    kill -9 $pids
    echo "All websocket connections closed."
fi

# Verify
sleep 1
remaining=$(ps aux | grep -i "python.*test.py" | grep -v grep)
if [ -z "$remaining" ]; then
    echo "✓ All connections successfully closed."
else
    echo "⚠ Some processes may still be running:"
    echo "$remaining"
fi
