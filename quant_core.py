"""Orchestratore quantitativo a 5 Agenti con Worker Pool parallelo e Asset Swap.

Modulo separato da trading_core.py (che resta la logica condivisa di app.py e
autonomous_market_scanner.py): qui vivono solo la pipeline degli agenti in
agents/ e la gestione in-memory degli slot di portafoglio.

Gli Scout dello sciame (trading_core.run_scout_swarm) convertono ogni scansione in un
payload standard (build_scout_payload) e lo inseriscono in una asyncio.Queue consumata
da process_scout_stream(): ogni fase degli agenti viene registrata a livello INFO su
console e su file (quant_agents.log nella cartella dati del bot).
"""
import asyncio
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from logging.handlers import RotatingFileHandler
from typing import Dict, Any, List, Optional, Union
import pandas as pd
import numpy as np

# Importazione degli Agenti della Cartella agents/
from agents.agent_01_quant import QuantEngineAgent
from agents.agent_02_micro import MicrostructureAgent
from agents.agent_03_risk import RiskManagerAgent
from agents.agent_04_macro import MacroSentimentAgent
from agents.agent_05_cio import CIOStrategistAgent

QUANT_LOG_PATH = os.path.join(os.getenv("BOT_DATA_DIR", os.path.dirname(os.path.abspath(__file__))), "quant_agents.log")
DEFAULT_ACCOUNT_BALANCE = 10000.0
STREAM_END = None   # sentinella: fine del pacchetto inviato dagli Scout sulla coda


def _build_logger() -> logging.Logger:
    """Logger dedicato agli agenti: console + file a rotazione, senza toccare il root logger dell'app."""
    log = logging.getLogger("quant_core")
    if log.handlers:
        return log
    log.setLevel(logging.INFO)
    log.propagate = False
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    log.addHandler(console)
    try:
        os.makedirs(os.path.dirname(QUANT_LOG_PATH), exist_ok=True)
        file_handler = RotatingFileHandler(QUANT_LOG_PATH, maxBytes=5_000_000, backupCount=3, encoding="utf-8")
        file_handler.setFormatter(fmt)
        log.addHandler(file_handler)
    except OSError as e:
        log.warning(f"Log su file non disponibile ({QUANT_LOG_PATH}): {e}")
    return log


logger = _build_logger()


def symbol_key(symbol: str) -> str:
    """Chiave di confronto unica (BTC-USD, BTC/USD e BTCUSD -> BTCUSD), come trading_core.normalize_symbol."""
    return str(symbol).upper().replace("-", "").replace("/", "")


def normalize_ohlcv(df: Optional[pd.DataFrame]) -> pd.DataFrame:
    """DataFrame con colonne minuscole open/high/low/close/volume (yfinance usa 'Close', 'Volume', ...)."""
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    out = df.rename(columns={c: str(c).strip().lower() for c in df.columns})
    out = out[[c for c in ("open", "high", "low", "close", "volume") if c in out.columns]]
    return out.apply(pd.to_numeric, errors="coerce").dropna(subset=[c for c in ("close",) if c in out.columns])


def build_scout_payload(
    symbol: str,
    df_ohlcv: Optional[pd.DataFrame],
    order_book: Optional[Dict[str, Any]] = None,
    macro_inputs: Optional[Dict[str, Any]] = None,
    account_balance: Optional[float] = None,
    scout_id: Optional[Union[int, str]] = None,
) -> Dict[str, Any]:
    """Payload standard che ogni Scout invia alla coda degli agenti.

    {"symbol": str, "df_ohlcv": DataFrame, "order_book": dict, "macro_inputs": dict,
     "account_balance": float} + "scout_id" per la tracciabilità nei log.
    """
    try:
        balance = float(account_balance) if account_balance is not None else DEFAULT_ACCOUNT_BALANCE
    except (TypeError, ValueError):
        balance = DEFAULT_ACCOUNT_BALANCE
    return {
        "symbol": str(symbol),
        "df_ohlcv": normalize_ohlcv(df_ohlcv),
        "order_book": dict(order_book or {}),
        "macro_inputs": dict(macro_inputs or {}),
        "account_balance": balance,
        "scout_id": scout_id if scout_id is not None else "?",
    }


def conviction_strength(cio_res: Dict[str, Any]) -> float:
    """
    Forza del segnale indipendente dalla direzione, sulla stessa scala 0-100
    dello score CIO: un BUY a 80 e un SELL a 20 valgono entrambi 80.
    Senza questa normalizzazione un SELL forte (score basso) risulterebbe
    sempre la posizione "più debole" e non potrebbe mai vincere uno swap.
    """
    score = cio_res.get("cio_ensemble_score", 50.0)
    return 100.0 - score if cio_res.get("final_decision") == "SELL" else score


def _fmt(value: Any, digits: int = 4) -> str:
    return f"{value:.{digits}f}" if isinstance(value, (int, float)) and not isinstance(value, bool) else str(value)


class QuantitativeTradingCore:
    """
    MOTORE PRINCIPALE DI TRADING QUANTITATIVO (Core Orchestrator)
    Gestisce l'ingestione parallela degli Scout, la pipeline dei 5 Agenti,
    il Capital Recycling (Asset Swap) e la sicurezza esecutiva.
    """
    def __init__(
        self,
        portfolio_max_slots: int = 3,
        num_workers: int = 4,
        swap_delta_threshold: float = 20.0
    ):
        self.portfolio_max_slots = portfolio_max_slots
        self.num_workers = num_workers
        self.swap_delta_threshold = swap_delta_threshold

        # Inizializzazione della squadra di Agenti (stateless: condivisibili tra i worker)
        self.agent_quant = QuantEngineAgent()
        self.agent_micro = MicrostructureAgent()
        self.agent_risk = RiskManagerAgent()
        self.agent_macro = MacroSentimentAgent()
        self.agent_cio = CIOStrategistAgent()

        # Worker Pool reale: gli agenti sono codice sincrono pandas/numpy, quindi
        # vanno eseguiti fuori dall'event loop per non bloccarlo.
        self.executor = ThreadPoolExecutor(max_workers=num_workers, thread_name_prefix="quant-worker")

        # Registro dello Stato del Portafoglio In-Memory (chiavi normalizzate, vedi symbol_key)
        self.active_portfolio: Dict[str, Dict[str, Any]] = {}
        # Ultima valutazione completa dei 5 agenti per simbolo (rationale delle operazioni)
        self.latest_evaluations: Dict[str, Dict[str, Any]] = {}
        self._eval_lock = threading.Lock()

    # ------------------------------------------------------------------ pipeline agenti
    def _run_agent(self, label: str, symbol: str, fn, fallback: Dict[str, Any]) -> Dict[str, Any]:
        """Esegue un agente: un'eccezione non viene silenziata ma registrata come Warning con la causa."""
        try:
            res = fn()
        except Exception as e:
            logger.warning(f"[{label}] ⚠️ {symbol} -> eccezione {type(e).__name__}: {e}")
            return {**fallback, "status": "AGENT_ERROR", "reason": f"{label} {type(e).__name__}: {e}"}
        if res.get("status") == "INSUFFICIENT_DATA":
            logger.warning(f"[{label}] ⚠️ {symbol} scartato -> dati insufficienti: {res.get('reason', 'N/D')}")
        return res

    def _run_agent_pipeline(self, worker_id: int, candidate_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Pipeline sincrona dei 5 agenti su un singolo candidato (eseguita in un thread del pool).
        """
        symbol = candidate_data.get("symbol")
        df_ohlcv = candidate_data.get("df_ohlcv")
        order_book = candidate_data.get("order_book") or {}
        macro_inputs = candidate_data.get("macro_inputs") or {}
        account_balance = candidate_data.get("account_balance", DEFAULT_ACCOUNT_BALANCE)

        if not symbol or not isinstance(df_ohlcv, pd.DataFrame):
            logger.warning(f"[Worker {worker_id}] ⚠️ Payload scartato: simbolo mancante o df_ohlcv non è un DataFrame "
                           f"(symbol={symbol!r}, df_ohlcv={type(df_ohlcv).__name__})")
            return None

        logger.info(f"[Worker {worker_id} | {threading.current_thread().name}] Avvio analisi {symbol} "
                    f"({len(df_ohlcv)} barre, book {'L2' if order_book.get('bids') else 'assente'})")

        # 1. Agente #1: Quant Engine
        res_quant = self._run_agent("AGENTE #1 QUANT", symbol, lambda: self.agent_quant.analyze(df_ohlcv),
                                    {"agent_id": self.agent_quant.agent_id, "quant_score": 50.0, "trade_signal": "NEUTRAL"})
        qm = res_quant.get("metrics", {})
        logger.info(f"[AGENTE #1 QUANT] 📊 {symbol} -> Hurst: {_fmt(qm.get('hurst_exponent', 'N/D'))}, "
                    f"GARCH Vol: {_fmt(qm['garch_vol_pct']) + '%' if 'garch_vol_pct' in qm else 'N/D'}, Z-Score: {_fmt(qm.get('z_score', 'N/D'))} "
                    f"-> Score: {_fmt(res_quant.get('quant_score'), 2)}")

        # 2. Agente #2: Microstructure & Order Flow
        res_micro = self._run_agent("AGENTE #2 MICRO", symbol, lambda: self.agent_micro.analyze(df_ohlcv, order_book=order_book),
                                    {"agent_id": self.agent_micro.agent_id, "microstructure_score": 50.0, "trade_signal": "NEUTRAL"})
        mm = res_micro.get("metrics", {})
        logger.info(f"[AGENTE #2 MICRO] 💧 {symbol} -> VPIN: {_fmt(mm.get('vpin_toxicity', 'N/D'))}, "
                    f"OFI: {_fmt(mm.get('order_flow_imbalance', 'N/D'))} ({mm.get('ofi_source', 'N/D')}) "
                    f"-> Score: {_fmt(res_micro.get('microstructure_score'), 2)}")

        # 3. Agente #3: Risk Manager
        res_risk = self._run_agent("AGENTE #3 RISK", symbol,
                                   lambda: self.agent_risk.analyze(df_ohlcv, account_balance=account_balance),
                                   {"agent_id": self.agent_risk.agent_id, "risk_approved": False, "risk_score": 0.0})
        stop = res_risk.get("position_parameters", {}).get("stop_loss_price", "N/D")
        logger.info(f"[AGENTE #3 RISK] 🛡️ {symbol} -> ATR Stop: {_fmt(stop)}, "
                    f"Risk Approved: {res_risk.get('risk_approved')} ({res_risk.get('reason', 'N/D')})")
        if not res_risk.get("risk_approved"):
            logger.warning(f"[AGENTE #3 RISK] ⚠️ {symbol} respinto dal Risk Manager: {res_risk.get('reason', 'N/D')}")

        # 4. Agente #4: Macro & Sentiment (Integra i dati presi da Groq/NLP)
        res_macro = self._run_agent("AGENTE #4 MACRO", symbol, lambda: self.agent_macro.analyze(
            df=df_ohlcv,
            vix_level=macro_inputs.get("vix_level", 16.5),
            fear_greed_index=macro_inputs.get("fear_greed_index", 50.0),
            news_sentiment=macro_inputs.get("news_sentiment", 0.0),
            central_bank_speech=macro_inputs.get("central_bank_speech", ""),
            upcoming_events=macro_inputs.get("upcoming_events", [])
        ), {"agent_id": self.agent_macro.agent_id, "macro_approved": False, "macro_score": 0.0, "stress_level": "UNKNOWN"})
        logger.info(f"[AGENTE #4 MACRO] 🌐 {symbol} -> Macro Stress: {res_macro.get('stress_level', 'N/D')}, "
                    f"Macro Approved: {res_macro.get('macro_approved')}"
                    + (f" ({res_macro['reason']})" if res_macro.get("reason") else ""))
        if not res_macro.get("macro_approved"):
            logger.warning(f"[AGENTE #4 MACRO] ⚠️ {symbol} respinto dall'Agente Macro: {res_macro.get('reason', 'N/D')}")

        # 5. Agente #5: CIO Synthesis Evaluation
        try:
            res_cio = self.agent_cio.synthesize(
                agent_01_quant_res=res_quant,
                agent_02_micro_res=res_micro,
                agent_03_risk_res=res_risk,
                agent_04_macro_res=res_macro
            )
        except Exception as e:
            logger.warning(f"[AGENTE #5 CIO] ⚠️ {symbol} scartato -> eccezione {type(e).__name__}: {e}")
            return None
        decision = res_cio.get("veto") or res_cio.get("final_decision")
        logger.info(f"[AGENTE #5 CIO] 👑 {symbol} -> Ensemble Score: {_fmt(res_cio.get('cio_ensemble_score'), 2)}/100 "
                    f"-> Decisione: {decision}" + (f" ({res_cio.get('reason')})" if res_cio.get("veto") else ""))

        result = {
            "symbol": symbol,
            "scout_id": candidate_data.get("scout_id"),
            "cio_result": res_cio,
            "raw_results": {
                "quant": res_quant,
                "micro": res_micro,
                "risk": res_risk,
                "macro": res_macro
            }
        }
        with self._eval_lock:
            self.latest_evaluations[symbol_key(symbol)] = {**result, "evaluated_at": time.time()}
        return result

    async def analyze_candidate_worker(self, worker_id: int, candidate_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Sottomette l'analisi di un singolo candidato Scout al Worker Pool.
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self.executor, self._run_agent_pipeline, worker_id, candidate_data)

    def rationale_for(self, symbol: str, max_age_sec: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """Punteggi dei 5 agenti sull'ultima valutazione del simbolo (None se assente o più vecchia di max_age_sec)."""
        with self._eval_lock:
            ev = self.latest_evaluations.get(symbol_key(symbol))
        if not ev or (max_age_sec is not None and time.time() - ev["evaluated_at"] > max_age_sec):
            return None
        raw, cio = ev["raw_results"], ev["cio_result"]
        return {
            "evaluated_at": ev["evaluated_at"],
            "agent_01_quant": {"score": raw["quant"].get("quant_score"), "signal": raw["quant"].get("trade_signal"),
                               "metrics": raw["quant"].get("metrics", {})},
            "agent_02_micro": {"score": raw["micro"].get("microstructure_score"), "signal": raw["micro"].get("trade_signal"),
                               "vpin": raw["micro"].get("metrics", {}).get("vpin_toxicity"),
                               "ofi": raw["micro"].get("metrics", {}).get("order_flow_imbalance")},
            "agent_03_risk": {"score": raw["risk"].get("risk_score"), "approved": raw["risk"].get("risk_approved"),
                              "reason": raw["risk"].get("reason"),
                              "stop_loss_price": raw["risk"].get("position_parameters", {}).get("stop_loss_price"),
                              "take_profit_price": raw["risk"].get("position_parameters", {}).get("take_profit_price")},
            "agent_04_macro": {"score": raw["macro"].get("macro_score"), "approved": raw["macro"].get("macro_approved"),
                               "stress_level": raw["macro"].get("stress_level")},
            "agent_05_cio": {"score": cio.get("cio_ensemble_score"), "decision": cio.get("veto") or cio.get("final_decision"),
                             "reason": cio.get("reason")},
        }

    # ------------------------------------------------------------------ allocazione
    def evaluate_capital_recycling_swap(self, new_opportunity: Dict[str, Any]) -> Dict[str, Any]:
        """
        Algoritmo di Asset Swap: determina se la nuova opportunità deve sostituire
        una posizione debole attiva in portafoglio.
        """
        symbol = new_opportunity["symbol"]
        cio_res = new_opportunity["cio_result"]
        new_strength = conviction_strength(cio_res)
        decision = cio_res.get("final_decision", "HOLD")

        if decision not in ["BUY", "SELL"]:
            return {"action": "REJECT", "reason": f"DECISION_IS_{decision}"}

        if symbol_key(symbol) in self.active_portfolio:
            return {"action": "REJECT", "reason": "ALREADY_IN_PORTFOLIO"}

        # Caso A: Il portafoglio ha ancora posti liberi
        if len(self.active_portfolio) < self.portfolio_max_slots:
            return {"action": "EXECUTE_NEW", "symbol": symbol, "reason": "SLOT_AVAILABLE"}

        # Caso B: Il portafoglio è pieno -> Cerca la posizione più debole per eventuale SWAP
        weakest_symbol = None
        lowest_strength = 999.0

        for active_sym, active_data in self.active_portfolio.items():
            active_strength = active_data.get("strength", 50.0)
            if active_strength < lowest_strength:
                lowest_strength = active_strength
                weakest_symbol = active_sym

        # Verifica della condizione di Swap Delta
        if weakest_symbol and new_strength > (lowest_strength + self.swap_delta_threshold):
            return {
                "action": "SWAP_POSITIONS",
                "close_symbol": weakest_symbol,
                "open_symbol": symbol,
                "delta_score": round(new_strength - lowest_strength, 2),
                "reason": f"HIGH_CONVICTION_SWAP (New: {new_strength} vs Old: {lowest_strength})"
            }

        return {
            "action": "REJECT",
            "reason": f"INSUFFICIENT_SWAP_DELTA (New: {new_strength} vs Lowest Active: {lowest_strength})"
        }

    def _register_position(self, symbol: str, cio_res: Dict[str, Any]) -> None:
        self.active_portfolio[symbol_key(symbol)] = {
            "symbol": symbol,
            "side": cio_res["final_decision"],
            "cio_ensemble_score": cio_res["cio_ensemble_score"],
            "strength": conviction_strength(cio_res),
            "details": cio_res
        }

    def _allocate(self, valid_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        # Le opportunità più forti occupano gli slot per prime: evita che un
        # candidato mediocre entri e venga subito swappato nello stesso batch.
        valid_results.sort(key=lambda r: conviction_strength(r["cio_result"]), reverse=True)

        execution_queue = []

        # Valutazione Allocazione del Capitale & Swap per ciascun risultato
        for item in valid_results:
            cio_res = item["cio_result"]
            if cio_res.get("final_decision") in ["BUY", "SELL"]:
                swap_decision = self.evaluate_capital_recycling_swap(item)

                if swap_decision["action"] == "EXECUTE_NEW":
                    logger.info(f"🟢 [APERTURA NUOVA] {item['symbol']} {cio_res['final_decision']} approvato con score {cio_res['cio_ensemble_score']}")
                    self._register_position(item["symbol"], cio_res)
                    execution_queue.append({"action": "OPEN", "data": item, "swap_info": swap_decision})

                elif swap_decision["action"] == "SWAP_POSITIONS":
                    close_sym = swap_decision["close_symbol"]
                    logger.info(f"🔄 [ASSET SWAP] Chiusura {close_sym} per apertura {item['symbol']} (Delta Score: {swap_decision['delta_score']})")

                    # Rimuovi il vecchio ed inserisci il nuovo
                    self.active_portfolio.pop(close_sym, None)
                    self._register_position(item["symbol"], cio_res)
                    execution_queue.append({"action": "SWAP", "data": item, "swap_info": swap_decision})

                else:
                    logger.info(f"⚪ [REJECTED] {item['symbol']} - {swap_decision['reason']}")
            else:
                label = cio_res.get("veto") or cio_res.get("final_decision")
                logger.info(f"⚪ [{label}] {item['symbol']} - {cio_res.get('reason')}")

        return execution_queue

    # ------------------------------------------------------------------ stream degli Scout
    async def _consume_queue(self, queue: asyncio.Queue) -> List[Dict[str, Any]]:
        """num_workers consumatori sulla coda finché non arriva la sentinella STREAM_END."""
        results: List[Dict[str, Any]] = []
        received = 0

        async def consumer(worker_id: int) -> None:
            nonlocal received
            while True:
                candidate = await queue.get()
                try:
                    if candidate is STREAM_END:
                        await queue.put(STREAM_END)   # la sentinella ferma anche gli altri consumatori
                        return
                    received += 1
                    logger.info(f"[SCOUT STREAM] 📨 Ricevuto candidato {candidate.get('symbol')} "
                                f"dallo Scout #{candidate.get('scout_id', '?')}")
                    res = await self.analyze_candidate_worker(worker_id, candidate)
                    if res is not None:
                        results.append(res)
                except Exception as e:
                    sym = candidate.get("symbol") if isinstance(candidate, dict) else repr(candidate)
                    logger.warning(f"[SCOUT STREAM] ⚠️ Candidato {sym} scartato per eccezione {type(e).__name__}: {e}")
                finally:
                    queue.task_done()

        await asyncio.gather(*(consumer(i) for i in range(self.num_workers)))
        logger.info(f"[SCOUT STREAM] Pacchetto completato: {received} candidati ricevuti, {len(results)} valutati dall'Agente #5")
        return results

    async def process_scout_stream(
        self, scout_stream: Union[asyncio.Queue, List[Dict[str, Any]]]
    ) -> List[Dict[str, Any]]:
        """
        Ingestione ed elaborazione ad alta velocità dei candidati Scout.

        scout_stream: asyncio.Queue alimentata dagli Scout (terminata da STREAM_END) oppure,
        per compatibilità, una lista già pronta di payload.
        """
        if isinstance(scout_stream, asyncio.Queue):
            logger.info(f"[SCOUT STREAM] In ascolto sulla coda degli Scout con {self.num_workers} Workers...")
            valid_results = await self._consume_queue(scout_stream)
        else:
            logger.info(f"Ricevuti {len(scout_stream)} candidati dagli Scout. Avvio elaborazione su {self.num_workers} Workers...")
            queue: asyncio.Queue = asyncio.Queue()
            for candidate in scout_stream:
                queue.put_nowait(candidate)
            queue.put_nowait(STREAM_END)
            valid_results = await self._consume_queue(queue)
        return self._allocate(valid_results)

    def shutdown(self) -> None:
        self.executor.shutdown(wait=True)


def dummy_ohlcv(seed: int, bars: int = 100) -> pd.DataFrame:
    """Barre OHLCV sintetiche per i test offline."""
    rng = np.random.default_rng(seed)
    close = rng.standard_normal(bars).cumsum() + 100
    open_ = close + rng.standard_normal(bars) * 0.3
    return pd.DataFrame({
        "open": open_,
        "high": np.maximum(open_, close) + rng.random(bars),
        "low": np.minimum(open_, close) - rng.random(bars),
        "close": close,
        "volume": rng.integers(100, 1000, bars)
    })


# ==============================================================================
# PIPELINE STREAMING DEMO / ENTRYPOINT
# ==============================================================================
if __name__ == "__main__":
    async def main():
        core = QuantitativeTradingCore(portfolio_max_slots=2, num_workers=4)
        queue: asyncio.Queue = asyncio.Queue()

        async def scouts():
            for i, sym in enumerate(["BTC/USDT", "ETH/USDT", "SOL/USDT", "AVAX/USDT"]):
                await queue.put(build_scout_payload(sym, dummy_ohlcv(i), account_balance=50000.0, scout_id=i + 1))
            await queue.put(STREAM_END)

        # Esecuzione Scansione Parallela e Gestione Portafoglio
        try:
            _, orders_to_execute = await asyncio.gather(scouts(), core.process_scout_stream(queue))
        finally:
            core.shutdown()
        print("\n--- PIANO ESECUTIVO GENERATO DALL'AGENTE #5 ---")
        for order in orders_to_execute:
            print(order["action"], order["data"]["symbol"], order["data"]["cio_result"]["final_decision"],
                  order["data"]["cio_result"]["cio_ensemble_score"], order["swap_info"])
        print("Portafoglio attivo:", {p["symbol"]: (p["side"], p["cio_ensemble_score"]) for p in core.active_portfolio.values()})

    asyncio.run(main())
