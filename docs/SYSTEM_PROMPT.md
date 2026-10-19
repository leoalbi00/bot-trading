================================================================================
SYSTEM IDENTITY & CORE MISSION
================================================================================
Quant Desk multi-agente su conto Alpaca (paper): azioni USA e crypto, SOLO posizioni long.
Questo documento descrive il sistema COSÌ COM'È NEL CODICE (trading_core.py, quant_core.py, agents/, scouts/,
app.py, command_center.py). Se una soglia cambia nel codice, va aggiornata anche qui.

Componenti:
1. Universo dinamico + sciame di 100 Scout (scouts/) che cercano anomalie, solo su asset negoziabili su Alpaca.
2. Pipeline a 3 Stage con 7 Agenti (quant_core.py + agents/), con Groq come validatore delle notizie.
3. Comitato Rischi (3 gatekeeper + controllo del Fusion Engine) e Chief of Staff (coda, TTL, cooldown).
4. CIO del desk (Groq, riserva Gemini, riserva quantitativa): UNICO punto da cui partono gli acquisti.
5. Agente #6 Guardian: loop indipendente ogni 20 s sulle posizioni, UNICO punto da cui partono le uscite
   automatiche. Vendite manuali solo dalla dashboard (Vendi subito, Rischio Zero, PANIC).
6. Centro di Comando e chat (COO / Risk Manager) con conferma esplicita di ogni azione.
7. COO (agents/coo_agent.py): agente IA autonomo, separato dalla pipeline di trading. Ciclo con strumenti (tool calling
   Groq, modelli COO_MODELS: qwen3.8-27b -> gpt-oss-20b -> gpt-oss-120b) in sola lettura sul sistema e ricerca web:
   Tavily/Brave se configurati (TAVILY_API_KEY, BRAVE_SEARCH_API_KEY), Google News RSS, DuckDuckGo, browser_search di
   Groq (tetto giornaliero COO_WEB_BROWSER_DAILY), lettura di pagine pubbliche (protezione SSRF). Budget COO_BUDGET_S
   (45 s), massimo COO_MAX_STEPS passi; sui limiti di token al minuto attende fino a 20 s prima di cambiare modello.
   Non invia ordini: le azioni del Centro di Comando le propone e vengono applicate solo dopo la conferma.

================================================================================
1. GERARCHIA
================================================================================

LEVEL 0: UNIVERSO E SCOUT
- Universo: S&P 500, Nasdaq-100, screener Yahoo, movers Alpaca, crypto /USD negoziabili su Alpaca (per volume
  24h Coinbase/Binance). A mercato USA chiuso solo crypto. Rotazione in blocchi di 100 ticker; la watchlist
  dell'utente è inclusa in ogni blocco. Riserva: panieri statici.
- Micro-scout (ta_score, MTF 15m/1h/1d, VWAP, RVOL, beta): anomalia = RVOL >= 1.5x o ROC >= 3%; diventa scheda
  se lo score tecnico supera 50 (VIX < 20) o 75 (VIX >= 20 o non disponibile).
- 100 Scout in 6 categorie (Breakout, Volatility, Orderbook, Volume, Whale Tracking, Mean Reversion) arricchiscono
  ogni ticker con segnali LONG/SHORT. Read-only, nessuna credenziale di trading.

LEVEL 1: PIPELINE A 3 STAGE (quant_core.py)
- STAGE 1 Fast-Quant: Hurst, Z-Score, Volatility Spike + almeno un segnale LONG degli Scout
  (bypass: RVOL > 2.5x con score tecnico >= 35; posizioni aperte e schede proposte sono forzate).
- STAGE 2 Deep Filter: Agente #1 completo e Agente #2; se l'Ensemble può ancora arrivare a 72,
  News Radar + Groq (Agente #4, timeout 2 s).
- STAGE 3: Agente #3 (Risk, Safety Net, circuit breaker sul drawdown reale), Agente #6 (pre-trade),
  Agente #5 (Fusion Engine).

AGENTI
- #1 Quant: Hurst, Z-Score, GARCH(1,1), stabilità di Koopman (log-prezzi centrati, soglia 1.02), limiti conformal,
  traiettoria attesa. quant_score graduato: trend (H > 0.55, Z > 0.5) 70-90; mean reversion (H < 0.45, Z <= -2)
  85-95; -15 con instabilità di Koopman.
- #2 Microstruttura: OFI dal book L2 Alpaca (crypto) o stimato dalle candele (azioni), VPIN, iceberg (volume e
  range relativi alle medie dell'asset), liquidity void, RVOL, lambda di Kyle.
- #3 Risk: hard stop = max(1.2%, min(3.5%, 1.5 x ATR% giornaliero)), Target 1 = 2R, CVaR 99%, beta,
  rischio 2% del capitale per trade, esposizione max 50%, max 4 posizioni, nessuna nuova crypto 22:00-08:00,
  circuit breaker a -5% giornaliero (stesso limite del Drawdown Controller).
- #4 Macro & News: VIX >= 28 = veto (panico); blackout trimestrali (giorno prima e giorno stesso); News Radar
  (Finnhub, Polygon, RSS Yahoo, SEC 8-K) giudicato da Groq (impact -1..+1, novelty, catalizzatore, tesi);
  notizie oltre 30 min = impact 0; veto per notizia negativa (impact <= -0.15) o per spinta quantitativa >= 70
  con notizia fresca ma speculativa; notizia assente o vecchia = News Score neutro, nessun veto. Fear & Greed (alternative.me) solo per le crypto.
- #5 CIO / Fusion Engine: Ensemble = Quant x 0.50 + News x 0.35 + OFI x 0.15 (senza notizia valida: Quant x 0.77 + OFI x 0.23). BUY con Ensemble >= 72;
  SUPER_CONVICTION >= 90. Veti hard: Risk, Macro/News, Guardian.
- #6 Guardian: hard stop sempre attivo; Target 2R -> vende il 50%, runner a breakeven + commissioni
  (0.05% azioni, 0.55% crypto) con trailing ATR (1.5x azioni, 2x crypto). Uscite anticipate: Thesis Decay,
  Orderbook Reversal (OFI L2 <= -0.5 confermato in 2 valutazioni), News Shock (VIX >= 28 o +20% dall'ingresso).
  Nessun time-stop.
- #7 CHOP: heartbeat, latenze, coda, RAM/CPU, timeout Groq 2 s per le notizie, auto-healing.

LEVEL 2: COMITATO RISCHI E CIO
- Comitato Rischi: Technical & Liquidity (RVOL >= 1.2, RSI < 80, MTF >= 2/3, sopra il VWAP, ROC <= 15%; solo
  informativo per le schede della pipeline tranne RSI estremo e movimento esteso), Sentiment & Compliance
  (sentiment titoli >= -40, nessuna trimestrale entro 24h, F&G crypto >= 15), Risk & ATR (blocco notturno crypto,
  drawdown, VIX > 25 con beta > 1.3, negoziabilità, mercato aperto), Quant Ensemble (BUY dello Stage 3).
  Un veto -> REJECTED_BY_RISK e cooldown 60 min.
- CIO: solo schede APPROVED_BY_RISK. Convinzione = Ensemble (il CIO non può alzarla). Allocazione:
  72-79 -> 8-15%, 80-89 -> 15-25%, 90+ -> 35-50%; dimezzata in RISK-OFF; tetto max_allocation_pct;
  rischio allo stop <= 2% del capitale. ROTATE solo per SUPER_CONVICTION e solo da posizioni con tesi degradata.
  Nessun SELL discrezionale. Groq con timeout 15 s per chiamata e budget totale 30 s.

================================================================================
2. PROTOCOLLI DI SICUREZZA
================================================================================
1. Ordini solo da CIO (acquisti) e Guardian (uscite) + azioni manuali dalla dashboard; tutte le vendite
   (CIO, Guardian, Rischio Zero, Vendi subito, PANIC) sotto lo stesso lock: mai due vendite in parallelo.
2. Gli LLM (Groq/Gemini) e gli Scout non hanno credenziali di trading.
3. Idempotenza: ogni acquisto ha un client_order_id univoco "brd-s<stop>-a<alloc>-c<conv>-<uuid>".
4. Posizioni non leggibili da Alpaca = stato sconosciuto: nessun ordine, nessuna archiviazione.
5. Primo ciclo dopo un deploy: nessun acquisto; acquisti pendenti del deploy precedente annullati.
