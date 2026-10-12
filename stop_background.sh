#!/bin/bash
cd "$(dirname "$0")"
if [ -f bot.pid ] && kill "$(cat bot.pid)" 2>/dev/null; then
    echo "Bot fermato (PID: $(cat bot.pid))."
else
    echo "Nessun bot in esecuzione."
fi
rm -f bot.pid
# Istanze residue del vecchio scanner autonomo (non più avviato dagli script)
pkill -f "autonomous_market_scanner.py" 2>/dev/null && echo "Scanner autonomo residuo fermato." || true
rm -f scanner.pid
