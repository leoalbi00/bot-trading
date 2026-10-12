#!/bin/bash
# Avvia la dashboard e il desk di trading (app.py) in background.
# NB: autonomous_market_scanner.py NON viene più avviato: era un secondo bot con una strategia diversa
# che inviava ordini in conflitto con il CIO e il Guardian.
cd "$(dirname "$0")"
if [ -f bot.pid ] && kill -0 "$(cat bot.pid)" 2>/dev/null; then
    echo "Bot già in esecuzione (PID: $(cat bot.pid))."
    exit 0
fi
nohup python3 -u app.py > bot.log 2>&1 &
echo $! > bot.pid
echo "Bot avviato in background! PID: $!"
