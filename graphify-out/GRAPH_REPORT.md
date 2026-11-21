# Graph Report - bot-trading  (2026-11-21)

## Corpus Check
- 39 files · ~78,245 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 6 file(s) not represented in the graph (top: (none) 4, .css 2)

## Summary
- 1166 nodes · 2495 edges · 66 communities (49 shown, 17 thin omitted)
- Extraction: 96% EXTRACTED · 4% INFERRED · 0% AMBIGUOUS · INFERRED: 88 edges (avg confidence: 0.87)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `8ba07469`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- app.py
- MacroSentimentAgent
- trading_core.py
- test_order_history.py
- _chat_context
- Any
- now_local
- PitchAuditRegister
- DynamicUniverseScreener
- _gstate_read
- ask_desk_cio
- HyperQuantAgent
- InstitutionalRiskAgent
- quant_core.py
- run_scout_swarm
- MicrostructureAgent
- graphify.yml
- PortfolioGuardianAgent
- ChopWatchdog
- numpy
- micro_scout
- buy_budget
- snapshot_state
- ScoutSwarm
- run_trading_cycle
- audit_board
- Any
- env_overrides
- read_json_file
- CIOStrategistAgent
- risk_limits
- desk
- quant_rationale
- core_allocation.py
- rotate_capital
- command_center.py
- QuantitativeTradingCore
- get_config
- chat
- update_config
- _decide
- pipeline_diagnosis
- require_login
- package.json
- portfolio_allocator.py
- parse_command
- initial_capital
- universe_chunk
- Piano di riorganizzazione del bot
- test_swarm_regressions.py
- .process_scout_stream
- _build_logger
- build_desk_cio_prompt
- .guarded_llm_call
- apply_trend_rank
- segment_matches
- snapshot_state
- prune_runtime_caches
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
6. `get_config()` - 29 edges
7. `now_local()` - 26 edges
8. `is_crypto()` - 24 edges
9. `ChopWatchdog` - 22 edges
10. `validate_desk_decision()` - 22 edges

## Surprising Connections (you probably didn't know these)
- `Dati e affidabilità` --references--> `log_message()`  [INFERRED]
  docs/PIANO_RIORGANIZZAZIONE.md → app.py
- `Organizzazione del codice` --references--> `run_trading_cycle()`  [INFERRED]
  docs/PIANO_RIORGANIZZAZIONE.md → app.py
- `Organizzazione del codice` --references--> `_decide()`  [INFERRED]
  docs/PIANO_RIORGANIZZAZIONE.md → command_center.py
- `Organizzazione del codice` --references--> `run_scout_swarm()`  [INFERRED]
  docs/PIANO_RIORGANIZZAZIONE.md → trading_core.py
- `5. Nuova organizzazione degli agenti` --references--> `validate_desk_decision()`  [INFERRED]
  docs/PIANO_RIORGANIZZAZIONE.md → trading_core.py

## Import Cycles
- None detected.

## Communities (66 total, 17 thin omitted)

### Community 0 - "app.py"
Cohesion: 0.08
Nodes (30): api_agent_control(), api_chat(), api_liquidate(), api_orders(), api_position_close(), api_settings_post(), api_toggle(), api_trigger() (+22 more)

### Community 1 - "MacroSentimentAgent"
Cohesion: 0.07
Nodes (9): build_news_prompt(), _epoch(), MacroSentimentAgent, NewsRadar, news(), test_negative_news_stays_a_veto(), chop_audit(), events_for_agents() (+1 more)

### Community 2 - "trading_core.py"
Cohesion: 0.05
Nodes (14): account_after_buy(), close_position_pct(), dialogue_head(), dynamic_volume_spikes(), _finnhub_headlines(), gate_technical_liquidity(), get_recent_news(), mark_user_seen() (+6 more)

### Community 3 - "test_order_history.py"
Cohesion: 0.13
Nodes (9): FakeAlpaca, test_api_orders_requires_token_and_validates_date(), test_order_history_classifies_core_bot_and_manual(), test_order_history_filters_symbol_and_returns_none_without_alpaca(), get_api_token(), get_dashboard_password(), get_secret_key(), order_history() (+1 more)

### Community 4 - "_chat_context"
Cohesion: 0.13
Nodes (12): account_with_pnl(), api_audit(), api_data(), api_position_detail(), cached(), _chat_context(), _find_position(), get_open_positions() (+4 more)

### Community 5 - "Any"
Cohesion: 0.05
Nodes (10): parse_news_assessment(), _rss_mb(), _clip(), COOAgent, _public_url(), _retry_after(), _strip_html(), WebResearch (+2 more)

### Community 6 - "now_local"
Cohesion: 0.09
Nodes (17): clamp_stop_pct(), hard_stop_pct(), test_trend_features_ignore_illiquid_and_todays_bar(), completed_daily_close(), dynamic_stop_pct(), _ema(), get_daily_bars(), guardian_evaluate() (+9 more)

### Community 7 - "PitchAuditRegister"
Cohesion: 0.15
Nodes (5): _key(), _num(), PitchAuditRegister, bucket(), _rate()

### Community 8 - "DynamicUniverseScreener"
Cohesion: 0.07
Nodes (7): DynamicUniverseScreener, release_memory(), _TimeoutAdapter, universe_chunk(), universe_screener(), with_http_timeout(), yf_missing()

### Community 9 - "_gstate_read"
Cohesion: 0.08
Nodes (15): _fallback_thesis(), _gstate_read(), _gstate_write(), guardian_position_state(), guardian_prune(), guardian_record_exit(), guardian_register_entry(), guardian_signals() (+7 more)

### Community 10 - "ask_desk_cio"
Cohesion: 0.13
Nodes (11): ask_desk_cio(), _ask_gemini(), _ask_groq(), _clean_number(), _clean_score(), groq_news_llm(), _no_ai_keys(), parse_broker_json() (+3 more)

### Community 11 - "HyperQuantAgent"
Cohesion: 0.14
Nodes (3): HyperQuantAgent, neg_log_likelihood(), variance_path()

### Community 13 - "quant_core.py"
Cohesion: 0.16
Nodes (4): ofi_to_score(), build_scout_payload(), looks_crypto(), normalize_ohlcv()

### Community 14 - "run_scout_swarm"
Cohesion: 0.07
Nodes (26): agent_say(), _audit_safe(), _close(), crypto_fear_greed(), crypto_order_books(), _daily_frames(), desk_universe(), _download() (+18 more)

### Community 16 - "graphify.yml"
Cohesion: 0.10
Nodes (20): concurrency, cancel-in-progress, group, jobs, update-graph, name, on, push (+12 more)

### Community 17 - "PortfolioGuardianAgent"
Cohesion: 0.12
Nodes (6): PortfolioGuardianAgent, _usd(), test_backtest_vix_exit_matches_guardian_rule(), test_guardian_moves_stop_to_breakeven_after_one_r(), test_guardian_trend_break_exit(), test_small_vix_rise_is_not_a_news_shock()

### Community 19 - "numpy"
Cohesion: 0.07
Nodes (23): core_returns(), mix(), stats(), daily_index(), effective_stop(), enter(), entries_allocator(), entries_current() (+15 more)

### Community 20 - "micro_scout"
Cohesion: 0.07
Nodes (17): atr_pct(), beta_correlation(), classify_score(), completed_bars(), compute_indicators(), get_indicators(), guardian_peak(), hourly_atr_pct() (+9 more)

### Community 21 - "buy_budget"
Cohesion: 0.15
Nodes (7): allocation_pct_for_score(), available_funds(), buy_budget(), _desk_cio_prompt_text(), desk_limits(), _fmt_pct(), max_exposure_pct()

### Community 22 - "snapshot_state"
Cohesion: 0.15
Nodes (11): api_agent_brain(), agents_snapshot(), blocks_text(), brief_state_text(), _clean(), logs(), diagnosis_lines(), _fmt() (+3 more)

### Community 24 - "run_trading_cycle"
Cohesion: 0.09
Nodes (20): api_position_de_risk(), deploy_liquidity(), describe_decision(), execute_buy(), guardian_tick(), journal_operation(), position_open_risk(), radar_loop() (+12 more)

### Community 25 - "audit_board"
Cohesion: 0.24
Nodes (7): audit_board(), fallback_votes(), _chop_health(), _db(), last_entry_execution(), list_executions(), _row_dict()

### Community 26 - "Any"
Cohesion: 0.18
Nodes (4): age_assessment(), conviction_strength(), _fmt(), symbol_key()

### Community 27 - "env_overrides"
Cohesion: 0.25
Nodes (5): settings(), config_sources(), env_overrides(), _parse_env_value(), public_config()

### Community 28 - "read_json_file"
Cohesion: 0.18
Nodes (7): current_drawdown(), drawdown_controller(), _intraday_equity_peak(), load_state(), read_json_file(), _review_context(), win_rates()

### Community 29 - "CIOStrategistAgent"
Cohesion: 0.17
Nodes (3): CIOStrategistAgent, test_full_portfolio_is_not_a_veto_so_no_cooldown(), test_trade_is_possible_without_news()

### Community 30 - "risk_limits"
Cohesion: 0.15
Nodes (12): risk_limits(), size_trade(), stop_pct(), test_core_position_is_invisible_to_guardian_and_radar(), test_crypto_cap(), test_cycle_reinvests_idle_cash_even_with_ai_on_hold(), test_cycle_with_core_buys_spy_and_keeps_the_bot_in_its_sleeve(), test_limits_shrink_with_regime_and_never_use_margin() (+4 more)

### Community 32 - "quant_rationale"
Cohesion: 0.13
Nodes (9): build_buy_thesis(), _ticker_detail(), _audit_close(), buy_thesis_for(), gate_quant_ensemble(), pitch_audit(), quant_rationale(), record_execution() (+1 more)

### Community 33 - "core_allocation.py"
Cohesion: 0.14
Nodes (11): is_core(), rebalance(), satellite_account(), split_positions(), target_value(), 2. Criticità trovate, Capitale e rischio, Dati e affidabilità (+3 more)

### Community 34 - "rotate_capital"
Cohesion: 0.18
Nodes (7): bot_account(), core_spy_pct(), fetch_bot_positions(), fetch_open_positions(), get_account_summary(), rotate_capital(), to_yf_symbol()

### Community 35 - "command_center.py"
Cohesion: 0.21
Nodes (10): _agent(), build_system_prompt(), chat_history(), _coo_tools(), rejected(), _fn(), _groq_client(), _llm_chat() (+2 more)

### Community 36 - "QuantitativeTradingCore"
Cohesion: 0.22
Nodes (4): dummy_ohlcv(), main(), QuantitativeTradingCore, test_pipeline_buys_a_trending_stock_without_news()

### Community 37 - "get_config"
Cohesion: 0.32
Nodes (14): account(), buy(), holding(), pitch(), test_ai_cannot_choose_the_size(), test_bot_never_buys_the_core_symbol(), test_exhausted_risk_budget_holds(), test_five_positions_block_new_buys() (+6 more)

### Community 38 - "chat"
Cohesion: 0.18
Nodes (7): _apply(), chat(), fallback_reply(), local_reply(), _precheck(), _propose(), _push()

### Community 39 - "update_config"
Cohesion: 0.22
Nodes (6): _load_config(), _read_config_file(), repo_defaults(), _save_config(), update_config(), _validate_config()

### Community 40 - "_decide"
Cohesion: 0.24
Nodes (9): clear_blocks(), _decide(), _default_state(), is_paused(), _load(), _save(), set_agent(), set_block() (+1 more)

### Community 41 - "pipeline_diagnosis"
Cohesion: 0.18
Nodes (6): _ago(), latest_channels(), pipeline_diagnosis(), _reason_key(), _registry_data(), _registry_view()

### Community 42 - "require_login"
Cohesion: 0.17
Nodes (10): _agent_feeds(), api_agents(), api_chat_history(), api_history(), api_settings_get(), has_valid_token(), require_login(), wrapper() (+2 more)

### Community 43 - "package.json"
Cohesion: 0.29
Nodes (9): dependencies, clsx@^2.1.1, framer-motion@^14.0.0, lightweight-charts@^5.2.1, lucide@^1.52.0, clsx, framer-motion, lightweight-charts (+1 more)

### Community 44 - "portfolio_allocator.py"
Cohesion: 0.12
Nodes (10): conviction_factor(), drawdown_scale(), open_risk_usd(), regime_scale(), trend_up_confirmed(), test_drawdown_scale(), test_missing_news_is_not_a_veto(), test_one_close_below_ema100_does_not_flip_the_regime() (+2 more)

### Community 45 - "parse_command"
Cohesion: 0.22
Nodes (6): propose(), describe_command(), normalize_command(), parse_command(), _rule_parse(), _segment_label()

### Community 46 - "initial_capital"
Cohesion: 0.25
Nodes (4): account_balance_for_agents(), equity_drawdown_pct(), initial_capital(), pnl_summary()

### Community 47 - "universe_chunk"
Cohesion: 0.17
Nodes (6): alpaca_order_symbol(), gate_risk_atr(), is_tradable(), risk_committee(), submit_notional_buy(), to_alpaca_symbol()

### Community 48 - "Piano di riorganizzazione del bot"
Cohesion: 0.14
Nodes (13): 1. In breve, 3. Strategie: cosa dicono gli studi, 3a. Metà "trading" (giorni-settimane): trend e momentum, 3b. Metà "day trading" (dentro la giornata, tutto chiuso entro le 15:55 di New York), 4. Divisione 50% / 50%, 5. Nuova organizzazione degli agenti, 6. Riorganizzazione del codice, 7. Grafica "a prova di bambino" (+5 more)

### Community 49 - "test_swarm_regressions.py"
Cohesion: 0.18
Nodes (5): _ok_gate(), test_idle_scouts_are_not_stalled(), test_refresh_held_evaluations_passes_real_exposure(), test_risk_committee_approves_when_vwap_is_unknown(), test_scout_timeout_ignores_waiting_in_queue()

### Community 52 - "build_desk_cio_prompt"
Cohesion: 0.25
Nodes (5): _long_pitch(), test_cio_prompt_accepts_unknown_vwap(), test_cio_prompt_fits_groq_free_tier_with_many_pitches(), build_desk_cio_prompt(), estimate_tokens()

### Community 54 - "apply_trend_rank"
Cohesion: 0.33
Nodes (4): test_rank_is_computed_on_the_universe(), test_score_outside_trend_never_enters(), apply_trend_rank(), trend_score()

### Community 55 - "segment_matches"
Cohesion: 0.40
Nodes (3): sector_of(), _segment_impact(), segment_matches()

### Community 56 - "snapshot_state"
Cohesion: 0.33
Nodes (4): api_blocks(), block_reason(), filter_inbox(), snapshot_state()

## Knowledge Gaps
- **17 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `QuantitativeTradingCore` connect `QuantitativeTradingCore` to `MacroSentimentAgent`, `trading_core.py`, `quant_core.py`, `MicrostructureAgent`, `PortfolioGuardianAgent`, `ChopWatchdog`, `.process_scout_stream`, `ScoutSwarm`, `Any`, `CIOStrategistAgent`?**
  _High betweenness centrality (0.097) - this node is a cross-community bridge._
- **Are the 2 inferred relationships involving `run_trading_cycle()` (e.g. with `api_trigger()` and `Organizzazione del codice`) actually correct?**
  _`run_trading_cycle()` has 2 INFERRED edges - model-reasoned connections that need verification._
- **Should `app.py` be split into smaller, more focused modules?**
  _Cohesion score 0.07547169811320754 - nodes in this community are weakly interconnected._
- **Why does `MacroSentimentAgent` connect `MacroSentimentAgent` to `QuantitativeTradingCore`, `Any`, `portfolio_allocator.py`, `quant_core.py`, `CIOStrategistAgent`, `risk_limits`?**
  _High betweenness centrality (0.045) - this node is a cross-community bridge._
- **Are the 2 inferred relationships involving `run_scout_swarm()` (e.g. with `Organizzazione del codice` and `run_one()`) actually correct?**
  _`run_scout_swarm()` has 2 INFERRED edges - model-reasoned connections that need verification._
- **Should `MacroSentimentAgent` be split into smaller, more focused modules?**
  _Cohesion score 0.06612244897959184 - nodes in this community are weakly interconnected._
- **Why does `ChopWatchdog` connect `ChopWatchdog` to `QuantitativeTradingCore`, `Any`, `quant_core.py`, `test_swarm_regressions.py`, `.guarded_llm_call`, `CIOStrategistAgent`?**
  _High betweenness centrality (0.041) - this node is a cross-community bridge._