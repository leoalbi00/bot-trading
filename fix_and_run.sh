#!/bin/bash
# Reinstalla le dipendenze, verifica la sintassi ed esegue un ciclo di test dello scanner.
# NB: non sovrascrive più il codice e ferma SOLO lo scanner (non tutti i processi python).
set -euo pipefail
cd "$(dirname "$0")"

echo "=== VERIFICA E AVVIO BOT ==="

# Arresta solo lo scanner in background, se attivo
./stop_background.sh || true

# Aggiornamento dipendenze
pip install -r requirements.txt > /dev/null

# Controllo sintassi
python3 -m py_compile app.py autonomous_market_scanner.py trading_core.py
echo "[✓] Sintassi Python OK"

# Avvio Test Immediato (un solo ciclo)
python3 autonomous_market_scanner.py
