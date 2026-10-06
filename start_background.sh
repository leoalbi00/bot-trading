#!/bin/bash
cd "$(dirname "$0")"
if [ -f scanner.pid ] && kill -0 "$(cat scanner.pid)" 2>/dev/null; then
    echo "Bot già in esecuzione (PID: $(cat scanner.pid))."
    exit 0
fi
nohup python3 -u autonomous_market_scanner.py --loop > bot.log 2>&1 &
echo $! > scanner.pid
echo "Bot avviato in background! PID: $!"
