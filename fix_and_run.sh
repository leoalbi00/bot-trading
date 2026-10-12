#!/bin/bash
# Reinstalla le dipendenze e verifica la sintassi. Non avvia più lo scanner autonomo (secondo bot in conflitto
# con il CIO e il Guardian) e non invia ordini: per avviare il desk usare start_background.sh.
set -euo pipefail
cd "$(dirname "$0")"

echo "=== VERIFICA BOT ==="

# Aggiornamento dipendenze
pip install -r requirements.txt > /dev/null

# Controllo sintassi
python3 -m py_compile app.py trading_core.py quant_core.py command_center.py agents/*.py scouts/*.py
echo "[✓] Sintassi Python OK"
