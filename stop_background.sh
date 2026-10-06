#!/bin/bash
cd "$(dirname "$0")"
if [ -f scanner.pid ] && kill "$(cat scanner.pid)" 2>/dev/null; then
    echo "Bot fermato (PID: $(cat scanner.pid))."
else
    pkill -f "autonomous_market_scanner.py" && echo "Bot fermato." || echo "Nessun bot in esecuzione."
fi
rm -f scanner.pid
