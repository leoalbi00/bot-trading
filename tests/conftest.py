"""I test non toccano Alpaca né le IA: credenziali vuote, modalità Advisor e nessun thread di trading."""
import os
import sys
import tempfile

_data = tempfile.mkdtemp(prefix="bot-tests-")
os.environ.update({
    "ALPACA_API_KEY": "", "ALPACA_SECRET_KEY": "", "GROQ_API_KEY": "", "GEMINI_API_KEY": "", "FINNHUB_API_KEY": "",
    "BOT_AUTO_EXECUTE": "false", "BOT_DATA_DIR": _data, "BOT_CONFIG_PATH": os.path.join(_data, "config.local.json"),
    "DASHBOARD_PASSWORD": "test", "FLASK_SECRET_KEY": "test", "BOT_API_TOKEN": "test", "SERVER_SOFTWARE": "gunicorn-test",
})
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
