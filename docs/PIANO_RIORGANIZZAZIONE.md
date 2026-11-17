# Piano di riorganizzazione del bot

Stato: **proposta da approvare**. Niente di questo documento è ancora nel codice.
Data dell'analisi: 17/11/2026, sul commit `e4979a4` (grafo graphify aggiornato: 1099 nodi, 2371 collegamenti).

---

## 1. In breve

Il bot funziona (39 test passano), ma è cresciuto per aggiunte successive e oggi ha tre problemi di fondo:

1. **Troppi pezzi che fanno la stessa cosa.** Due "CIO", quattro livelli di controllo del rischio, uno sciame di
   100 Scout più tre Stage più un ensemble per decidere se comprare un titolo. È difficile capire chi decide cosa.
2. **Nessuna strategia con un vantaggio dimostrato.** Il backtest del 3 novembre dice che il solo SPY ha reso più
   di ogni combinazione con il bot. Lo sciame aggiunge complessità senza prove che migliori i risultati.
3. **Il capitale è usato male.** 76% fermo su SPY senza stop (oggi circa −2,8k), il resto diviso in 15 posizioni
   piccole che restano aperte finché non toccano lo stop.

La proposta: **due strategie semplici e documentate da studi pubblici, 50% del capitale ciascuna**, sette ruoli
chiari al posto di quindici moduli, codice diviso per responsabilità, e una dashboard che spiega ogni numero.

---

## 2. Criticità trovate

Gravità: 🔴 alta (soldi o dati a rischio) · 🟠 media (risultati peggiori) · 🟡 bassa (ordine, manutenzione).

### Capitale e rischio
| # | Gravità | Problema | Dove |
|---|---|---|---|
| 1 | 🔴 | **Core SPY all'80% senza stop.** Il Guardian non lo vede; l'unica uscita è il cambio di regime dopo 3 chiusure sotto la EMA100. Il 76% del conto segue SPY in tutto e per tutto, comprese le discese. | `agents/core_allocation.py`, `app.py:147` |
| 2 | 🔴 | **Vendite e riacquisti enormi a ogni cambio di regime**: circa il 50% del capitale venduto e poi ricomprato. Se SPY oscilla intorno alla media, il conto perde a ogni giro. | `core_allocation.rebalance` (verificato con simulazione) |
| 3 | 🟠 | **Il bot lavora sul 20% del capitale diviso fino a 15 posizioni**: ogni posizione vale al massimo il 3% del conto, spesso meno. | `portfolio_allocator.py` (`MAX_POSITIONS = 15`) |
| 4 | 🟠 | **Le posizioni non si liberano.** Le uscite sono solo del Guardian (stop, target, trend); niente uscita a tempo. La rotazione scatta solo se la tesi è "degradata". Con 15 posti pieni le occasioni nuove vengono scartate. | `app.py` (ciclo CIO), `validate_desk_decision` |
| 5 | 🟡 | **Impostazioni che sembrano non fare nulla**: `stop_loss_pct: -5` e `watchlist` in `config.json` convivono con stop dinamici e universo dinamico. Chi legge la config si fa un'idea sbagliata. | `config.json`, `trading_core.py:122-150` |

### Dati e affidabilità
| # | Gravità | Problema | Dove |
|---|---|---|---|
| 6 | 🔴 | **I log stanno solo in memoria** e lo stato in file JSON sul disco di Render, che si azzera a ogni deploy salvo disco persistente. Per questo non abbiamo potuto ricostruire il caso SPY. | `app.py:53` (`log_message`), `DATA_DIR` |
| 7 | 🟠 | **Tutti i prezzi vengono da yfinance**, servizio non ufficiale che può rallentare o bloccare. Per il day trading servono barre da 1–5 minuti affidabili: yfinance non basta. | `trading_core.py` (download) |
| 8 | 🟠 | **Il "flusso ordini" dell'Agente #2 è reale solo per le crypto.** Per le azioni è stimato da candele orarie, ma il nome ("HFT Engine", VPIN, iceberg) fa pensare a dati che non ci sono. | `agents/agent_02_micro.py`, `trading_core.py:3646` |

### Organizzazione del codice
| # | Gravità | Problema | Dove |
|---|---|---|---|
| 9 | 🟠 | **`trading_core.py` ha 4.091 righe e 189 funzioni**: dati, strategie, rischio, ordini, LLM, registri, tutto insieme. | `trading_core.py` |
| 10 | 🟠 | **Il trading gira dentro il server web**: un solo processo gunicorn con 5 thread (ciclo CIO, radar, Guardian, CHOP, keep-alive). Un problema del sito può fermare il trading e viceversa. | `app.py:861-865`, `Procfile` |
| 11 | 🟡 | **Funzioni enormi**: `run_scout_swarm` 248 righe, `run_trading_cycle` 206, `_run_agent_pipeline` 192, `_decide` 163. | grafo: nodi più collegati |
| 12 | 🟡 | **Due "CIO" diversi** (Agente #5 ensemble e "Desk CIO" con LLM + fallback quantitativo) e **quattro livelli di rischio** (Agente #3, Portfolio Allocator, `validate_desk_decision`, Drawdown Controller). | `agents/agent_05_cio.py`, `trading_core.py` |
| 13 | 🟡 | **Test concentrati su un solo file** (39 test): ciclo principale, ordini e sciame quasi senza test. | `tests/` |

---

## 3. Strategie: cosa dicono gli studi

Prima un avvertimento onesto: gli studi su larga scala dicono che **la maggior parte di chi fa day trading perde
soldi**. A Taiwan meno dell'1% dei day trader batte il mercato con continuità; in Brasile il 97% di chi ha insistito
per più di 300 giorni ha perso (Barber, Lee, Liu, Odean; Chague et al.). Le strategie qui sotto hanno risultati
pubblicati, ma sono **simulazioni sul passato**: vanno provate in paper per mesi prima di usare soldi veri.

### 3a. Metà "trading" (giorni-settimane): trend e momentum
| Strategia | Prove | Perché la scelgo |
|---|---|---|
| **Momentum relativo** (comprare i titoli più forti degli ultimi 6-12 mesi) | Effetto documentato da decenni; il bot lo usa già (rank ≥ 0,70) | È l'unica parte del bot già validata nei backtest |
| **Momentum assoluto / trend following** (stare investiti solo se il mercato è sopra la sua media) | Moskowitz, Ooi, Pedersen (2012): positivo su tutti i 58 mercati studiati; Hurst, Ooi, Pedersen: un secolo di dati | Sostituisce il core SPY senza stop: quando SPY è sotto trend si va in liquidità o titoli di Stato a breve, non si resta esposti al 76% |
| **Dual momentum** (le due cose insieme) | Antonacci; Faber (media a 10 mesi) | Regola semplice, spiegabile a chiunque |

Proposta concreta: ogni settimana si scelgono i **6-10 titoli più forti** di un universo liquido. Se ne trovano meno,
il resto va su SPY **solo se SPY è in trend**, altrimenti in liquidità o ETF di titoli di Stato a breve. Stop e
uscite restano quelli del Portfolio Allocator, già validati.

### 3b. Metà "day trading" (dentro la giornata, tutto chiuso entro le 15:55 di New York)
| Strategia | Prove | Note |
|---|---|---|
| **Opening Range Breakout a 5 minuti su "stocks in play"** (titoli con volume anomalo, di solito per una notizia) | Zarattini, Barbon, Aziz (2024): oltre 7.000 titoli 2016-2023, Sharpe 2,81 in backtest; replica indipendente QuantConnect Sharpe 2,4 | Il miglior candidato. Rischio 1% per operazione, stop al 10% dell'ATR, uscita a fine giornata |
| **Trend intraday con VWAP su SPY/QQQ** | Zarattini, Aziz (2023-2024): batte il buy & hold su SPY e QQQ in backtest | Alternativa semplice quando non ci sono stocks in play |
| **Momentum intraday** (la prima mezz'ora predice l'ultima) | Gao, Han, Li, Zhou, *JFE* 2018 | Effetto piccolo (1-2% della varianza) e più debole nelle repliche: solo come filtro, non come strategia |

Cosa serve per il day trading:
- **Barre da 1-5 minuti affidabili**: API dati di Alpaca (feed IEX gratuito) al posto di yfinance.
- **Un ciclo ogni minuto** durante la seduta, separato dal ciclo lento.
- **Nessuna leva**: gli studi usano fino a 4x, noi no.
- **Regola PDT**: il minimo di $25.000 è stato abolito dal 4 giugno 2026 (FINRA, Rule 4210), ma i broker possono
  adeguarsi fino a ottobre 2027. Va verificato cosa applica Alpaca al tuo conto.

Le crypto le toglierei dalla prima versione: aggiungono un mercato 24/7 con regole diverse e nessuno dei due studi
le copre. Si possono reintrodurre dopo.

---

## 4. Divisione 50% / 50%

Due "salvadanai" con contabilità separata, come oggi core e satellite:

| | Trading (lento) | Day trading (veloce) |
|---|---|---|
| Capitale | 50% del conto | 50% del conto |
| Quando lavora | Ribilanciamento settimanale + Guardian sempre | Solo 9:30-15:55 New York (15:30-21:55 in Italia) |
| Posizioni | 6-10 | 0-4 al giorno, tutte chiuse a fine seduta |
| Rischio | Stop del Portfolio Allocator | 1% del suo capitale per operazione, perdita massima giornaliera 3% |
| Riconoscimento ordini | `client_order_id` con prefisso `swing-` | prefisso `day-` |

Un controllo blocca qualsiasi ordine di un salvadanaio che userebbe i soldi dell'altro. Ogni mese si confronta
ciascun salvadanaio con SPY: se dopo 3 mesi in paper una strategia fa peggio di SPY, si ferma e se ne discute.

---

## 5. Nuova organizzazione degli agenti

Da 15 moduli a **7 ruoli**, ognuno con un compito solo e un nome comprensibile anche in dashboard.

| Nuovo ruolo | Cosa fa | Da cosa nasce |
|---|---|---|
| **1. Osservatore di mercato** | Scarica e controlla i dati (giornalieri e intraday), costruisce l'universo dei titoli liquidi, trova gli "stocks in play" | Universe Screener + caricamento dati dello sciame |
| **2. Stratega lento** | Classifica per momentum, applica il filtro di trend, propone il portafoglio della settimana | Agente #1 Quant + Portfolio Allocator (parte strategia) |
| **3. Stratega veloce** | Opening range, VWAP, segnali di ingresso intraday | Nuovo (spunti da `trader-entry`/`trader-exit` di day-trader-skill) |
| **4. Lettore di notizie** | Notizie e comunicazioni SEC: conferma gli stocks in play e blocca titoli con eventi pericolosi (es. trimestrale in giornata) | Agente #4 Macro/News |
| **5. Controllore del rischio** | **Unico cancello**: dimensione, perdita massima, limiti giornalieri, separazione 50/50. Dice PASSA o BLOCCA con il motivo | Agente #3 + Allocator (parte rischio) + Drawdown Controller + `validate_desk_decision` (spunti da `trader-risk`) |
| **6. Esecutore e Guardiano** | Unico punto che invia ordini; segue le posizioni, gestisce stop, target e chiusura di fine giornata | Execution Desk + Agente #6 Guardian |
| **7. Ispettore** | Vedi sotto | CHOP Watchdog + HR Audit + COO (parte diagnosi) |

Cosa sparisce o si fonde:
- **Sciame di 100 Scout e pipeline a 3 Stage**: sostituiti dagli scanner dei due strateghi. Nessuna prova che migliorino i risultati, molta complessità.
- **Agente #2 Microstruttura**: per le azioni non ha dati reali di order book. Il volume relativo (RVOL), l'unica parte utile, passa all'Osservatore.
- **Agente #5 CIO e "Desk CIO" con LLM**: le decisioni diventano regole fisse, verificabili con il backtest. L'LLM (Groq/Gemini gratuiti) resta per spiegare e per le notizie, non per decidere gli acquisti.

### L'Ispettore, più forte di quello proposto prima
Non solo controlli fissi, ma **confronto continuo tra ciò che il bot dovrebbe fare e ciò che fa davvero**:
- **Riconciliazione** a ogni ciclo: posizioni e ordini su Alpaca contro il registro interno, per salvadanaio. Ogni differenza è un allarme.
- **Ordini ripetuti**: stesso titolo comprato più volte in poco tempo (il caso SPY), ordini respinti in serie.
- **Strategia contro realtà**: ogni settimana rifà il backtest sullo stesso periodo vissuto in paper. Se i risultati divergono troppo c'è un errore (dati, esecuzione o codice) e lo segnala con i numeri.
- **Perdite fuori dal normale**: una posizione o un salvadanaio che perde più di quanto il modello di rischio permette.
- **Configurazione**: valori diversi tra dashboard, `config.json` e variabili di Render.
- **Salute**: dati vecchi, servizi esterni lenti, thread fermi (quello che fa oggi il CHOP Watchdog).
- **Spiegazione**: ogni allarme ha una frase semplice ("Ho visto che SPY è stato comprato 3 volte oggi: non dovrebbe succedere più di una volta"), scritta dall'LLM gratuito con i numeri reali.
- **Memoria**: tutto finisce in un database permanente, non più in memoria.

---

## 6. Riorganizzazione del codice

```
bot/
  data/         prezzi giornalieri e intraday (Alpaca + yfinance di riserva), universo
  strategies/   slow.py (momentum + trend), fast.py (ORB + VWAP)
  risk/         controllore unico, regole 50/50
  execution/    ordini, Guardian, riconciliazione
  monitor/      Ispettore, log permanenti, report
  explain/      testi semplici per dashboard e chat (LLM gratuito)
web/            Flask: solo pagine e API, nessuna logica di trading
worker.py       processo separato che fa girare i cicli
```

- **Processo web e processo di trading separati** (`Procfile`: `web` + `worker`). Su Render il worker è un
  servizio a parte: va verificato il costo del tuo piano.
- **Database permanente** per log, ordini e allarmi: SQLite su disco persistente di Render, oppure Postgres.
  Da scegliere in base al piano Render.
- **Backtest su GitHub Actions**: qui la rete blocca Yahoo, mentre su GitHub i dati si scaricano. Ogni modifica a
  una strategia lancia il backtest e allega i risultati alla PR.

---

## 7. Grafica "a prova di bambino"

Obiettivo: chi non ha mai visto un grafico di borsa capisce **cosa vede, perché lo vede e cosa sta pensando il bot**.

Principi:
1. **Una domanda per schermata.** Home: "Come stanno i miei soldi oggi?" con 3 numeri: totale, guadagno o perdita di oggi, confronto con SPY.
2. **Ogni riquadro ha tre righe fisse**: *Cosa vedi* · *Perché è così* · *Cosa fa il bot adesso*.
3. **Due salvadanai disegnati come tali**: "Investimenti lenti" e "Operazioni di giornata", ognuno con il suo saldo e il suo semaforo.
4. **Diario delle decisioni in frasi intere**: "Ho comprato 12 azioni di Apple a 231 $ perché negli ultimi 6 mesi è tra le più forti e il mercato è in salita. Se scende a 219 $ la vendo."
5. **Niente gergo senza spiegazione**: ATR, R, VWAP, momentum hanno sempre un "?" con una frase semplice. Le sigle interne (OFI, VPIN, Stage) spariscono.
6. **Semafori** (verde / giallo / rosso) solo su ciò che richiede attenzione; il resto è grigio e calmo.
7. **Telefono prima di tutto**: la usi soprattutto da lì.

Skill installate per questo lavoro (in `.claude/skills/`):
- `dashboard-design`: regole per dashboard chiare (una domanda per schermo, numeri onesti, stati vuoti, controllo con screenshot). Da adattare: vorrebbe zero frasi fuori dai tooltip, noi invece vogliamo la riga "perché" sempre visibile.
- `ui-ux-pro-max`: archivio locale di stili, palette, abbinamenti di font, linee guida UX e tipi di grafico.
- `frontend-design`, `web-design-guidelines`, `webapp-testing`: già installate; disegno, controllo accessibilità, test automatici con screenshot.
- `dataviz`: già disponibile in Claude Code, per i grafici.

---

## 8. Fasi di lavoro

Ogni fase finisce con test che passano e, dove cambia una strategia, un backtest confrontato con SPY.

| Fase | Contenuto | Condizione per passare alla successiva |
|---|---|---|
| **0. Messa in sicurezza** | Decidere subito sul core SPY all'80%; log e stato su database permanente | Log che sopravvivono a un riavvio |
| **1. Ispettore** | Riconciliazione, ordini ripetuti, configurazione, salute, spiegazioni | Ritrova da solo il caso SPY sui dati salvati |
| **2. Riordino del codice** | Nuova struttura, worker separato, **senza cambiare il comportamento** | Stessi risultati del codice attuale su un ciclo registrato |
| **3. Strategia lenta** | Dual momentum sul 50% | Backtest 2016-2026 migliore di SPY a parità di rischio, poi 4 settimane di paper |
| **4. Strategia veloce** | ORB + VWAP sul 50%, dati Alpaca a 1-5 minuti | Backtest sugli anni disponibili, poi 3 mesi di paper |
| **5. Nuova dashboard** | Grafica a prova di bambino | Test con screenshot da telefono; una persona estranea al trading la capisce |
| **6. Pulizia** | Rimozione di sciame, agenti fusi e impostazioni morte | Grafo graphify più piccolo, test verdi |

---

## 9. Decisioni che servono da te

1. **Core SPY oggi**: lo spengo subito (0%) in attesa della nuova strategia lenta, o lo lascio?
2. **Approvi i 7 ruoli** al posto degli agenti attuali? Puoi cambiare nomi e compiti.
3. **Crypto fuori** dalla prima versione?
4. **Render**: hai un disco persistente o un database? E il piano consente un secondo servizio (il worker)?
5. **Chiavi dati Alpaca**: il bot le ha già per il conto paper; vanno bene anche per i dati intraday (feed IEX gratuito).

---

## Fonti
- Zarattini, Barbon, Aziz (2024), *A Profitable Day Trading Strategy For The U.S. Equity Market*: https://concretumgroup.com/a-profitable-day-trading-strategy-for-the-u-s-equity-market/ · https://ideas.repec.org/p/chf/rpseri/rp2498.html
- Replica QuantConnect dell'ORB: https://www.quantconnect.com/research/18444/opening-range-breakout-for-stocks-in-play/
- Zarattini, Aziz, *VWAP: The Holy Grail for Day Trading Systems*: https://concretumgroup.com/volume-weighted-average-price-vwap-the-holy-grail-for-day-trading-systems/
- Gao, Han, Li, Zhou (2018), *Market Intraday Momentum*, JFE: https://econpapers.repec.org/RePEc:eee:jfinec:v:129:y:2018:i:2:p:394-414
- Moskowitz, Ooi, Pedersen (2012), *Time Series Momentum*: https://papers.ssrn.com/abstract=2089463
- Faber e dual momentum, sintesi: https://quantpedia.com/Screener/Details/1
- Barber, Lee, Liu, Odean, day trading a Taiwan: https://faculty.haas.berkeley.edu/odean/papers/day%20traders/day%20trading%20and%20learning%20110217.pdf
- Regola PDT abolita (Federal Register, 17/04/2026): https://www.govinfo.gov/content/pkg/FR-2026-04-17/html/2026-07485.htm
