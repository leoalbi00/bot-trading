# Letto automaticamente da gunicorn (anche quando il comando di avvio di Render non usa il Procfile).
# Un solo worker: lo stato del bot è in memoria e il loop di trading non deve essere duplicato.
workers = 1
threads = 4
timeout = 120


def post_worker_init(worker):
    # Avvia i thread di trading/Keep-Alive nel worker appena pronto, senza attendere una richiesta
    import app
    app.start_background_threads()
