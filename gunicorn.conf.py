# Letto automaticamente da gunicorn (anche quando il comando di avvio di Render non usa il Procfile).
# Un solo worker: lo stato del bot è in memoria e il loop di trading non deve essere duplicato.
workers = 1
# 8 thread: una richiesta lenta durante una raffica dello sciame non blocca /ping e /api/agents
threads = 8
timeout = 120


def post_worker_init(worker):
    # Avvia i thread di trading/Keep-Alive nel worker appena pronto, senza attendere una richiesta
    import app
    app.start_background_threads()
