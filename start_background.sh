#!/bin/bash
nohup python3 autonomous_market_scanner.py > bot.log 2>&1 &
echo "Bot avviato in background! PID: $!"
