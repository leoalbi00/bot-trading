"""Orchestratore quantitativo a 5 Agenti con Worker Pool parallelo e Asset Swap.

Modulo separato da trading_core.py (che resta la logica condivisa di app.py e
autonomous_market_scanner.py): qui vivono solo la pipeline degli agenti in
agents/ e la gestione in-memory degli slot di portafoglio.
"""
import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any, List, Optional
import pandas as pd
import numpy as np

# Importazione degli Agenti della Cartella agents/
from agents.agent_01_quant import QuantEngineAgent
from agents.agent_02_micro import MicrostructureAgent
from agents.agent_03_risk import RiskManagerAgent
from agents.agent_04_macro import MacroSentimentAgent
from agents.agent_05_cio import CIOStrategistAgent

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def conviction_strength(cio_res: Dict[str, Any]) -> float:
    """
    Forza del segnale indipendente dalla direzione, sulla stessa scala 0-100
    dello score CIO: un BUY a 80 e un SELL a 20 valgono entrambi 80.
    Senza questa normalizzazione un SELL forte (score basso) risulterebbe
    sempre la posizione "più debole" e non potrebbe mai vincere uno swap.
    """
    score = cio_res.get("cio_ensemble_score", 50.0)
    return 100.0 - score if cio_res.get("final_decision") == "SELL" else score


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

        # Registro dello Stato del Portafoglio In-Memory
        self.active_portfolio: Dict[str, Dict[str, Any]] = {}
        self.opportunity_queue: asyncio.Queue = asyncio.Queue()

    def _run_agent_pipeline(self, worker_id: int, candidate_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Pipeline sincrona dei 5 agenti su un singolo candidato (eseguita in un thread del pool).
        """
        symbol = candidate_data.get("symbol")
        df_ohlcv = candidate_data.get("df_ohlcv")
        order_book = candidate_data.get("order_book", {})
        macro_inputs = candidate_data.get("macro_inputs", {})

        try:
            # 1. Agente #1: Quant Engine
            res_quant = self.agent_quant.analyze(df_ohlcv)

            # 2. Agente #2: Microstructure & Order Flow
            res_micro = self.agent_micro.analyze(df_ohlcv, order_book=order_book)

            # 3. Agente #3: Risk Manager
            res_risk = self.agent_risk.analyze(df_ohlcv, account_balance=candidate_data.get("account_balance", 10000.0))

            # 4. Agente #4: Macro & Sentiment (Integra i dati presi da Groq/NLP)
            res_macro = self.agent_macro.analyze(
                df=df_ohlcv,
                vix_level=macro_inputs.get("vix_level", 16.5),
                fear_greed_index=macro_inputs.get("fear_greed_index", 50.0),
                news_sentiment=macro_inputs.get("news_sentiment", 0.0),
                central_bank_speech=macro_inputs.get("central_bank_speech", ""),
                upcoming_events=macro_inputs.get("upcoming_events", [])
            )

            # 5. Agente #5: CIO Synthesis Evaluation
            res_cio = self.agent_cio.synthesize(
                agent_01_quant_res=res_quant,
                agent_02_micro_res=res_micro,
                agent_03_risk_res=res_risk,
                agent_04_macro_res=res_macro
            )

            return {
                "symbol": symbol,
                "cio_result": res_cio,
                "raw_results": {
                    "quant": res_quant,
                    "micro": res_micro,
                    "risk": res_risk,
                    "macro": res_macro
                }
            }

        except Exception as e:
            logging.error(f"[Worker {worker_id}] Errore durante l'analisi di {symbol}: {str(e)}")
            return None

    async def analyze_candidate_worker(self, worker_id: int, candidate_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Sottomette l'analisi di un singolo candidato Scout al Worker Pool.
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self.executor, self._run_agent_pipeline, worker_id, candidate_data)

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

        if symbol in self.active_portfolio:
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
        self.active_portfolio[symbol] = {
            "side": cio_res["final_decision"],
            "cio_ensemble_score": cio_res["cio_ensemble_score"],
            "strength": conviction_strength(cio_res),
            "details": cio_res
        }

    async def process_scout_stream(self, scout_candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Ingestione ed elaborazione ad alta velocità di un pacchetto illimitato di candidati Scout.
        """
        logging.info(f"Ricevuti {len(scout_candidates)} candidati dagli Scout. Avvio elaborazione su {self.num_workers} Workers...")

        tasks = []
        for idx, candidate in enumerate(scout_candidates):
            worker_id = idx % self.num_workers
            tasks.append(self.analyze_candidate_worker(worker_id, candidate))

        # Esecuzione Parallela (il pool limita la concorrenza a num_workers)
        analyzed_results = await asyncio.gather(*tasks)
        valid_results = [r for r in analyzed_results if r is not None]

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
                    logging.info(f"🟢 [APERTURA NUOVA] {item['symbol']} {cio_res['final_decision']} approvato con score {cio_res['cio_ensemble_score']}")
                    self._register_position(item["symbol"], cio_res)
                    execution_queue.append({"action": "OPEN", "data": item, "swap_info": swap_decision})

                elif swap_decision["action"] == "SWAP_POSITIONS":
                    close_sym = swap_decision["close_symbol"]
                    logging.info(f"🔄 [ASSET SWAP] Chiusura {close_sym} per apertura {item['symbol']} (Delta Score: {swap_decision['delta_score']})")

                    # Rimuovi il vecchio ed inserisci il nuovo
                    self.active_portfolio.pop(close_sym, None)
                    self._register_position(item["symbol"], cio_res)
                    execution_queue.append({"action": "SWAP", "data": item, "swap_info": swap_decision})

                else:
                    logging.info(f"⚪ [REJECTED] {item['symbol']} - {swap_decision['reason']}")
            else:
                logging.info(f"⚪ [{cio_res.get('final_decision')}] {item['symbol']} - {cio_res.get('reason')}")

        return execution_queue

    def shutdown(self) -> None:
        self.executor.shutdown(wait=True)


# ==============================================================================
# PIPELINE STREAMING DEMO / ENTRYPOINT
# ==============================================================================
if __name__ == "__main__":
    async def main():
        core = QuantitativeTradingCore(portfolio_max_slots=2, num_workers=4)

        # Generazione Dati Simulati per il test di elaborazione illimitata degli Scout
        def dummy_df(seed: int) -> pd.DataFrame:
            rng = np.random.default_rng(seed)
            close = rng.standard_normal(100).cumsum() + 100
            open_ = close + rng.standard_normal(100) * 0.3
            return pd.DataFrame({
                "open": open_,
                "high": np.maximum(open_, close) + rng.random(100),
                "low": np.minimum(open_, close) - rng.random(100),
                "close": close,
                "volume": rng.integers(100, 1000, 100)
            })

        mock_scout_batch = [
            {"symbol": sym, "df_ohlcv": dummy_df(i), "account_balance": 50000.0}
            for i, sym in enumerate(["BTC/USDT", "ETH/USDT", "SOL/USDT", "AVAX/USDT"])
        ]

        # Esecuzione Scansione Parallela e Gestione Portafoglio
        try:
            orders_to_execute = await core.process_scout_stream(mock_scout_batch)
        finally:
            core.shutdown()
        print("\n--- PIANO ESECUTIVO GENERATO DALL'AGENTE #5 ---")
        for order in orders_to_execute:
            print(order["action"], order["data"]["symbol"], order["data"]["cio_result"]["final_decision"],
                  order["data"]["cio_result"]["cio_ensemble_score"], order["swap_info"])
        print("Portafoglio attivo:", {s: (p["side"], p["cio_ensemble_score"]) for s, p in core.active_portfolio.items()})

    asyncio.run(main())
