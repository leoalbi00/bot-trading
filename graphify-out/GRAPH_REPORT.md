# Graph Report - bot-trading  (2026-11-20)

## Corpus Check
- 39 files · ~77,073 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 6 file(s) not represented in the graph (top: (none) 4, .css 2)

## Summary
- 1145 nodes · 2454 edges · 63 communities (49 shown, 14 thin omitted)
- Extraction: 97% EXTRACTED · 3% INFERRED · 0% AMBIGUOUS · INFERRED: 83 edges (avg confidence: 0.87)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `4b8e338a`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- agent_say
- MacroSentimentAgent
- trading_core.py
- portfolio_sim.py
- app.py
- Any
- now_local
- PitchAuditRegister
- DynamicUniverseScreener
- normalize_symbol
- quant_core.py
- HyperQuantAgent
- InstitutionalRiskAgent
- quant_core.py
- run_scout_swarm
- MicrostructureAgent
- graphify.yml
- PortfolioGuardianAgent
- ChopWatchdog
- detectors.py
- micro_scout
- risk_committee
- snapshot_state
- ScoutSwarm
- run_trading_cycle
- pitch_audit
- QuantitativeTradingCore
- _coo_tools
- read_json_file
- log_message
- risk_limits
- test_portfolio_allocator.py
- quant_engine
- core_allocation.py
- rotate_capital
- command_center.py
- gate_sentiment_compliance
- get_config
- chat
- update_config
- _decide
- pipeline_diagnosis
- core_satellite.py
- package.json
- drawdown_scale
- parse_command
- initial_capital
- universe_chunk
- Piano di riorganizzazione del bot
- agent_04_macro.py
- swarm_baskets
- _build_logger
- _fallback_thesis
- apply_trend_rank
- segment_matches
- git_sync_status.sh
- fix_and_run.sh
- start_background.sh
- stop_background.sh

## God Nodes (most connected - your core abstractions)
1. `run_trading_cycle()` - 51 edges
2. `normalize_symbol()` - 45 edges
3. `run_scout_swarm()` - 33 edges
4. `log_message()` - 32 edges
5. `QuantitativeTradingCore` - 29 edges
6. `get_config()` - 28 edges
7. `now_local()` - 26 edges
8. `is_crypto()` - 24 edges
9. `validate_desk_decision()` - 22 edges
10. `MacroSentimentAgent` - 21 edges

## Surprising Connections (you probably didn't know these)
- `Dati e affidabilità` --references--> `log_message()`  [INFERRED]
  docs/PIANO_RIORGANIZZAZIONE.md → app.py
- `Capitale e rischio` --references--> `rebalance()`  [INFERRED]
  docs/PIANO_RIORGANIZZAZIONE.md → agents/core_allocation.py
- `Organizzazione del codice` --references--> `run_trading_cycle()`  [INFERRED]
  docs/PIANO_RIORGANIZZAZIONE.md → app.py
- `Organizzazione del codice` --references--> `_decide()`  [INFERRED]
  docs/PIANO_RIORGANIZZAZIONE.md → command_center.py
- `Organizzazione del codice` --references--> `run_scout_swarm()`  [INFERRED]
  docs/PIANO_RIORGANIZZAZIONE.md → trading_core.py

## Import Cycles
- None detected.

## Communities (63 total, 14 thin omitted)

### Community 0 - "agent_say"
Cohesion: 0.10
Nodes (16): api_agent_control(), api_blocks(), api_chat(), api_liquidate(), api_position_close(), api_settings_post(), api_toggle(), api_trigger() (+8 more)

### Community 1 - "MacroSentimentAgent"
Cohesion: 0.08
Nodes (5): build_news_prompt(), _epoch(), MacroSentimentAgent, NewsRadar, test_negative_news_stays_a_veto()

### Community 2 - "trading_core.py"
Cohesion: 0.06
Nodes (15): ask_desk_cio(), _ask_gemini(), _ask_groq(), _clean_number(), _clean_score(), dialogue_head(), groq_news_llm(), mark_user_seen() (+7 more)

### Community 3 - "portfolio_sim.py"
Cohesion: 0.18
Nodes (9): daily_index(), effective_stop(), enter(), entries_allocator(), entries_current(), exits_trend(), load_data(), Market (+1 more)

### Community 4 - "app.py"
Cohesion: 0.08
Nodes (29): account_with_pnl(), _agent_feeds(), api_agent_brain(), api_agents(), api_audit(), api_chat_history(), api_data(), api_history() (+21 more)

### Community 5 - "Any"
Cohesion: 0.10
Nodes (6): _clip(), COOAgent, _public_url(), _retry_after(), _strip_html(), WebResearch

### Community 6 - "now_local"
Cohesion: 0.08
Nodes (18): test_trend_features_ignore_illiquid_and_todays_bar(), completed_daily_close(), dynamic_stop_pct(), _ema(), get_daily_bars(), guardian_evaluate(), guardian_signals(), guardian_trend_break() (+10 more)

### Community 7 - "PitchAuditRegister"
Cohesion: 0.15
Nodes (5): _key(), _num(), PitchAuditRegister, bucket(), _rate()

### Community 8 - "DynamicUniverseScreener"
Cohesion: 0.10
Nodes (3): DynamicUniverseScreener, _TimeoutAdapter, with_http_timeout()

### Community 9 - "normalize_symbol"
Cohesion: 0.09
Nodes (18): api_position_de_risk(), guardian_tick(), journal_operation(), radar_loop(), request_cio(), account(), get_pending_order_symbols(), _gstate_read() (+10 more)

### Community 11 - "HyperQuantAgent"
Cohesion: 0.14
Nodes (3): HyperQuantAgent, neg_log_likelihood(), variance_path()

### Community 12 - "InstitutionalRiskAgent"
Cohesion: 0.06
Nodes (11): crypto_night_blocked(), InstitutionalRiskAgent, FakeAlpaca, test_api_orders_requires_token_and_validates_date(), test_order_history_classifies_core_bot_and_manual(), test_order_history_filters_symbol_and_returns_none_without_alpaca(), get_api_token(), get_dashboard_password() (+3 more)

### Community 13 - "quant_core.py"
Cohesion: 0.14
Nodes (4): clamp_stop_pct(), hard_stop_pct(), ofi_to_score(), stats()

### Community 14 - "run_scout_swarm"
Cohesion: 0.07
Nodes (24): _audit_safe(), cio_inbox(), _close(), crypto_fear_greed(), crypto_order_books(), _daily_frames(), _download(), earnings_within() (+16 more)

### Community 16 - "graphify.yml"
Cohesion: 0.10
Nodes (20): concurrency, cancel-in-progress, group, jobs, update-graph, name, on, push (+12 more)

### Community 17 - "PortfolioGuardianAgent"
Cohesion: 0.13
Nodes (5): PortfolioGuardianAgent, _usd(), test_guardian_moves_stop_to_breakeven_after_one_r(), test_guardian_trend_break_exit(), test_small_vix_rise_is_not_a_news_shock()

### Community 19 - "detectors.py"
Cohesion: 0.20
Nodes (9): _atr(), breakout(), hurst_exponent(), mean_reversion(), orderbook(), _signal(), volatility(), volume() (+1 more)

### Community 20 - "micro_scout"
Cohesion: 0.06
Nodes (18): atr_pct(), beta_correlation(), classify_score(), completed_bars(), compute_indicators(), get_indicators(), guardian_atr(), guardian_atr_info() (+10 more)

### Community 21 - "risk_committee"
Cohesion: 0.08
Nodes (14): _ok_gate(), test_cio_prompt_accepts_unknown_vwap(), test_refresh_held_evaluations_passes_real_exposure(), test_risk_committee_approves_when_vwap_is_unknown(), allocation_pct_for_score(), available_funds(), build_desk_cio_prompt(), buy_budget() (+6 more)

### Community 22 - "snapshot_state"
Cohesion: 0.13
Nodes (14): agents_snapshot(), block_reason(), blocks_text(), brief_state_text(), build_system_prompt(), _clean(), logs(), diagnosis_lines() (+6 more)

### Community 24 - "run_trading_cycle"
Cohesion: 0.10
Nodes (14): deploy_liquidity(), describe_decision(), execute_buy(), position_open_risk(), run_trading_cycle(), set_ai_analysis(), account_after_buy(), buy_thesis_for() (+6 more)

### Community 25 - "pitch_audit"
Cohesion: 0.13
Nodes (12): audit_board(), fallback_votes(), _audit_close(), _audit_stages(), _chop_health(), _db(), last_entry_execution(), list_executions() (+4 more)

### Community 26 - "QuantitativeTradingCore"
Cohesion: 0.05
Nodes (16): build_buy_thesis(), CIOStrategistAgent, age_assessment(), build_scout_payload(), conviction_strength(), dummy_ohlcv(), _fmt(), looks_crypto() (+8 more)

### Community 27 - "_coo_tools"
Cohesion: 0.22
Nodes (6): _coo_tools(), rejected(), settings(), _fn(), _ticker_detail(), public_config()

### Community 28 - "read_json_file"
Cohesion: 0.18
Nodes (7): current_drawdown(), drawdown_controller(), _intraday_equity_peak(), load_state(), read_json_file(), _review_context(), win_rates()

### Community 29 - "log_message"
Cohesion: 0.15
Nodes (10): background_loop(), chop_loop(), ensure_background_threads(), guardian_loop(), keep_alive_loop(), keep_alive_url(), log_message(), should_abort() (+2 more)

### Community 30 - "risk_limits"
Cohesion: 0.13
Nodes (10): conviction_factor(), risk_limits(), size_trade(), stop_pct(), test_crypto_cap(), test_limits_shrink_with_regime_and_never_use_margin(), test_more_volatile_titles_get_less_capital(), test_position_limit_is_five() (+2 more)

### Community 31 - "test_portfolio_allocator.py"
Cohesion: 0.13
Nodes (10): open_risk_usd(), trend_up_confirmed(), desk(), test_core_position_is_invisible_to_guardian_and_radar(), test_cycle_reinvests_idle_cash_even_with_ai_on_hold(), test_cycle_with_core_buys_spy_and_keeps_the_bot_in_its_sleeve(), test_liquidity_wakes_the_cio(), test_one_close_below_ema100_does_not_flip_the_regime() (+2 more)

### Community 32 - "quant_engine"
Cohesion: 0.29
Nodes (4): news(), chop_audit(), events_for_agents(), quant_engine()

### Community 33 - "core_allocation.py"
Cohesion: 0.19
Nodes (7): is_core(), rebalance(), satellite_account(), split_positions(), target_value(), test_core_rebalances_only_outside_the_band(), test_satellite_account_hides_the_core_cash()

### Community 34 - "rotate_capital"
Cohesion: 0.14
Nodes (8): bot_account(), core_spy_pct(), fetch_bot_positions(), fetch_open_positions(), rebalance_core(), rotate_capital(), submit_core_order(), wait_for_fill()

### Community 35 - "command_center.py"
Cohesion: 0.33
Nodes (6): _agent(), chat_history(), _groq_client(), _llm_chat(), pending_proposal(), _web_research()

### Community 36 - "gate_sentiment_compliance"
Cohesion: 0.29
Nodes (4): _finnhub_headlines(), gate_sentiment_compliance(), get_recent_news(), sentiment_score()

### Community 37 - "get_config"
Cohesion: 0.32
Nodes (14): account(), buy(), holding(), pitch(), test_ai_cannot_choose_the_size(), test_bot_never_buys_the_core_symbol(), test_exhausted_risk_budget_holds(), test_five_positions_block_new_buys() (+6 more)

### Community 38 - "chat"
Cohesion: 0.14
Nodes (9): _apply(), chat(), describe_command(), fallback_reply(), local_reply(), _precheck(), _propose(), _push() (+1 more)

### Community 39 - "update_config"
Cohesion: 0.15
Nodes (9): config_sources(), env_overrides(), _load_config(), _parse_env_value(), _read_config_file(), repo_defaults(), _save_config(), update_config() (+1 more)

### Community 40 - "_decide"
Cohesion: 0.24
Nodes (9): clear_blocks(), _decide(), _default_state(), is_paused(), _load(), _save(), set_agent(), set_block() (+1 more)

### Community 41 - "pipeline_diagnosis"
Cohesion: 0.14
Nodes (7): _ago(), latest_channels(), pipeline_diagnosis(), radar_snapshot(), _reason_key(), _registry_data(), _registry_view()

### Community 42 - "core_satellite.py"
Cohesion: 0.17
Nodes (3): core_returns(), mix(), stats()

### Community 43 - "package.json"
Cohesion: 0.29
Nodes (9): dependencies, clsx@^2.1.1, framer-motion@^14.0.0, lightweight-charts@^5.2.1, lucide@^1.52.0, clsx, framer-motion, lightweight-charts (+1 more)

### Community 44 - "drawdown_scale"
Cohesion: 0.25
Nodes (5): drawdown_scale(), regime_scale(), test_drawdown_scale(), test_missing_news_is_not_a_veto(), test_regime_scale()

### Community 45 - "parse_command"
Cohesion: 0.33
Nodes (4): propose(), normalize_command(), parse_command(), _rule_parse()

### Community 46 - "initial_capital"
Cohesion: 0.25
Nodes (4): account_balance_for_agents(), equity_drawdown_pct(), initial_capital(), pnl_summary()

### Community 47 - "universe_chunk"
Cohesion: 0.12
Nodes (9): alpaca_order_symbol(), gate_risk_atr(), is_tradable(), release_memory(), submit_notional_buy(), to_alpaca_symbol(), universe_chunk(), universe_screener() (+1 more)

### Community 48 - "Piano di riorganizzazione del bot"
Cohesion: 0.11
Nodes (17): 1. In breve, 2. Criticità trovate, 3. Strategie: cosa dicono gli studi, 3a. Metà "trading" (giorni-settimane): trend e momentum, 3b. Metà "day trading" (dentro la giornata, tutto chiuso entro le 15:55 di New York), 4. Divisione 50% / 50%, 5. Nuova organizzazione degli agenti, 6. Riorganizzazione del codice (+9 more)

### Community 49 - "agent_04_macro.py"
Cohesion: 0.27
Nodes (3): parse_news_assessment(), blocked_name(), main()

### Community 50 - "swarm_baskets"
Cohesion: 0.33
Nodes (3): desk_universe(), dynamic_volume_spikes(), swarm_baskets()

### Community 54 - "apply_trend_rank"
Cohesion: 0.33
Nodes (4): test_rank_is_computed_on_the_universe(), test_score_outside_trend_never_enters(), apply_trend_rank(), trend_score()

### Community 55 - "segment_matches"
Cohesion: 0.40
Nodes (3): sector_of(), _segment_impact(), segment_matches()

## Knowledge Gaps
- **14 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `QuantitativeTradingCore` connect `QuantitativeTradingCore` to `quant_engine`, `MacroSentimentAgent`, `trading_core.py`, `quant_core.py`, `MicrostructureAgent`, `PortfolioGuardianAgent`, `ChopWatchdog`, `ScoutSwarm`?**
  _High betweenness centrality (0.113) - this node is a cross-community bridge._
- **Are the 2 inferred relationships involving `run_trading_cycle()` (e.g. with `api_trigger()` and `Organizzazione del codice`) actually correct?**
  _`run_trading_cycle()` has 2 INFERRED edges - model-reasoned connections that need verification._
- **Should `agent_say` be split into smaller, more focused modules?**
  _Cohesion score 0.09686609686609686 - nodes in this community are weakly interconnected._
- **Why does `MacroSentimentAgent` connect `MacroSentimentAgent` to `drawdown_scale`, `quant_core.py`, `agent_04_macro.py`, `QuantitativeTradingCore`, `test_portfolio_allocator.py`?**
  _High betweenness centrality (0.046) - this node is a cross-community bridge._
- **Are the 2 inferred relationships involving `run_scout_swarm()` (e.g. with `Organizzazione del codice` and `run_one()`) actually correct?**
  _`run_scout_swarm()` has 2 INFERRED edges - model-reasoned connections that need verification._
- **Should `MacroSentimentAgent` be split into smaller, more focused modules?**
  _Cohesion score 0.08194905869324474 - nodes in this community are weakly interconnected._
- **Why does `PortfolioGuardianAgent` connect `PortfolioGuardianAgent` to `trading_core.py`, `now_local`, `quant_core.py`, `QuantitativeTradingCore`, `test_portfolio_allocator.py`?**
  _High betweenness centrality (0.038) - this node is a cross-community bridge._