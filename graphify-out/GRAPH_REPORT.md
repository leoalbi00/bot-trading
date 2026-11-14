# Graph Report - bot-trading  (2026-11-14)

## Corpus Check
- 36 files · ~71,676 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 4 file(s) not represented in the graph (top: (none) 3, .css 1)

## Summary
- 1099 nodes · 2371 edges · 67 communities (49 shown, 18 thin omitted)
- Extraction: 97% EXTRACTED · 3% INFERRED · 0% AMBIGUOUS · INFERRED: 74 edges (avg confidence: 0.86)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `d5bab45a`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- app.py
- MacroSentimentAgent
- trading_core.py
- run_scout_swarm
- _chat_context
- coo_agent.py
- normalize_symbol
- PitchAuditRegister
- DynamicUniverseScreener
- api_position_de_risk
- quant_core.py
- HyperQuantAgent
- InstitutionalRiskAgent
- quant_engine
- is_tradable
- MicrostructureAgent
- graphify.yml
- PortfolioGuardianAgent
- ChopWatchdog
- detectors.py
- micro_scout
- numpy
- snapshot_state
- ScoutSwarm
- route
- pitch_audit
- QuantitativeTradingCore
- ask_desk_cio
- completed_daily_close
- read_json_file
- risk_limits
- test_portfolio_allocator.py
- api_agent_brain
- core_allocation.py
- os
- command_center.py
- get_api_token
- get_config
- chat
- update_config
- _decide
- pipeline_diagnosis
- risk_manager
- package.json
- _warn_throttled
- describe_command
- numpy
- drawdown_scale
- universe_chunk
- initial_capital
- _build_logger
- pitch_audit
- compute_indicators
- apply_trend_rank
- prune_runtime_caches
- segment_matches
- allocation_pct_for_score
- api_position_close
- git_sync_status.sh
- fix_and_run.sh
- start_background.sh
- stop_background.sh
- pitch_conviction

## God Nodes (most connected - your core abstractions)
1. `run_trading_cycle()` - 50 edges
2. `normalize_symbol()` - 44 edges
3. `run_scout_swarm()` - 32 edges
4. `log_message()` - 30 edges
5. `QuantitativeTradingCore` - 29 edges
6. `get_config()` - 26 edges
7. `now_local()` - 26 edges
8. `is_crypto()` - 24 edges
9. `MacroSentimentAgent` - 21 edges
10. `agent_say()` - 20 edges

## Surprising Connections (you probably didn't know these)
- `QuantitativeTradingCore` --uses--> `MacroSentimentAgent`  [INFERRED]
  quant_core.py → agents/agent_04_macro.py
- `test_missing_news_is_not_a_veto()` --uses--> `MacroSentimentAgent`  [INFERRED]
  tests/test_portfolio_allocator.py → agents/agent_04_macro.py
- `QuantitativeTradingCore` --uses--> `NewsRadar`  [INFERRED]
  quant_core.py → agents/agent_04_macro.py
- `QuantitativeTradingCore` --uses--> `MicrostructureAgent`  [INFERRED]
  quant_core.py → agents/agent_02_micro.py
- `QuantitativeTradingCore` --uses--> `PortfolioGuardianAgent`  [INFERRED]
  quant_core.py → agents/agent_06_sentinel.py

## Import Cycles
- None detected.

## Communities (67 total, 18 thin omitted)

### Community 0 - "app.py"
Cohesion: 0.07
Nodes (30): api_liquidate(), api_trigger(), background_loop(), bot_account(), chop_loop(), core_spy_pct(), deploy_liquidity(), describe_decision() (+22 more)

### Community 1 - "MacroSentimentAgent"
Cohesion: 0.08
Nodes (5): build_news_prompt(), _epoch(), MacroSentimentAgent, NewsRadar, test_negative_news_stays_a_veto()

### Community 2 - "trading_core.py"
Cohesion: 0.04
Nodes (15): account_after_buy(), available_funds(), dialogue_head(), dynamic_volume_spikes(), _finnhub_headlines(), gate_technical_liquidity(), get_recent_news(), mark_user_seen() (+7 more)

### Community 3 - "run_scout_swarm"
Cohesion: 0.06
Nodes (30): agent_say(), _audit_safe(), cio_inbox(), _close(), crypto_fear_greed(), crypto_order_books(), _daily_frames(), desk_universe() (+22 more)

### Community 4 - "_chat_context"
Cohesion: 0.18
Nodes (9): account_with_pnl(), api_data(), cached(), _chat_context(), _find_position(), get_open_positions(), positions_with_allocation(), guardian_snapshot() (+1 more)

### Community 5 - "coo_agent.py"
Cohesion: 0.10
Nodes (6): _clip(), COOAgent, _public_url(), _retry_after(), _strip_html(), WebResearch

### Community 6 - "normalize_symbol"
Cohesion: 0.07
Nodes (23): api_position_detail(), dynamic_stop_pct(), gate_quant_ensemble(), _gstate_read(), _gstate_write(), guardian_atr(), guardian_atr_info(), guardian_evaluate() (+15 more)

### Community 7 - "PitchAuditRegister"
Cohesion: 0.15
Nodes (5): _key(), _num(), PitchAuditRegister, bucket(), _rate()

### Community 8 - "DynamicUniverseScreener"
Cohesion: 0.10
Nodes (3): DynamicUniverseScreener, _TimeoutAdapter, with_http_timeout()

### Community 9 - "api_position_de_risk"
Cohesion: 0.19
Nodes (8): api_position_de_risk(), guardian_tick(), journal_operation(), radar_loop(), request_cio(), close_position_pct(), get_pending_order_symbols(), is_market_open()

### Community 11 - "HyperQuantAgent"
Cohesion: 0.14
Nodes (3): HyperQuantAgent, neg_log_likelihood(), variance_path()

### Community 13 - "quant_engine"
Cohesion: 0.18
Nodes (6): news(), chop_audit(), events_for_agents(), guardian_signals(), _ofi_exit_signal(), quant_engine()

### Community 14 - "is_tradable"
Cohesion: 0.25
Nodes (4): alpaca_order_symbol(), is_tradable(), submit_notional_buy(), to_alpaca_symbol()

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
Cohesion: 0.09
Nodes (13): atr_pct(), beta_correlation(), classify_score(), completed_bars(), get_indicators(), hourly_atr_pct(), indicators_on_closed_bars(), market_analyst() (+5 more)

### Community 21 - "numpy"
Cohesion: 0.15
Nodes (10): daily_index(), effective_stop(), enter(), entries_allocator(), entries_current(), exits_trend(), load_data(), Market (+2 more)

### Community 22 - "snapshot_state"
Cohesion: 0.16
Nodes (11): block_reason(), blocks_text(), brief_state_text(), build_system_prompt(), settings(), diagnosis_lines(), filter_inbox(), _fmt() (+3 more)

### Community 24 - "route"
Cohesion: 0.08
Nodes (24): _agent_feeds(), api_agent_control(), api_agents(), api_audit(), api_chat(), api_history(), api_settings_get(), api_settings_post() (+16 more)

### Community 25 - "pitch_audit"
Cohesion: 0.16
Nodes (9): audit_board(), fallback_votes(), _chop_health(), _db(), _fallback_thesis(), last_entry_execution(), list_executions(), _row_dict() (+1 more)

### Community 26 - "QuantitativeTradingCore"
Cohesion: 0.05
Nodes (17): build_buy_thesis(), CIOStrategistAgent, age_assessment(), build_scout_payload(), conviction_strength(), dummy_ohlcv(), _fmt(), looks_crypto() (+9 more)

### Community 27 - "ask_desk_cio"
Cohesion: 0.22
Nodes (7): ask_desk_cio(), _ask_gemini(), _ask_groq(), _clean_number(), _clean_score(), parse_broker_json(), parse_desk_decision()

### Community 28 - "completed_daily_close"
Cohesion: 0.15
Nodes (10): trend_up_confirmed(), test_one_close_below_ema100_does_not_flip_the_regime(), test_trend_features_ignore_illiquid_and_todays_bar(), completed_daily_close(), _ema(), get_daily_bars(), guardian_trend_break(), macro_channel() (+2 more)

### Community 29 - "read_json_file"
Cohesion: 0.14
Nodes (9): current_drawdown(), drawdown_controller(), _intraday_equity_peak(), load_state(), read_json_file(), _review_context(), save_state(), win_rates() (+1 more)

### Community 30 - "risk_limits"
Cohesion: 0.14
Nodes (9): conviction_factor(), risk_limits(), size_trade(), stop_pct(), test_crypto_cap(), test_limits_shrink_with_regime_and_never_use_margin(), test_more_volatile_titles_get_less_capital(), test_size_never_exceeds_cap_or_cash_floor() (+1 more)

### Community 31 - "test_portfolio_allocator.py"
Cohesion: 0.17
Nodes (8): open_risk_usd(), desk(), test_core_position_is_invisible_to_guardian_and_radar(), test_cycle_reinvests_idle_cash_even_with_ai_on_hold(), test_cycle_with_core_buys_spy_and_keeps_the_bot_in_its_sleeve(), test_liquidity_wakes_the_cio(), test_open_risk_of_a_runner_is_smaller(), with_core()

### Community 32 - "api_agent_brain"
Cohesion: 0.33
Nodes (5): api_agent_brain(), agents_snapshot(), _clean(), logs(), thoughts_for()

### Community 33 - "core_allocation.py"
Cohesion: 0.19
Nodes (7): is_core(), rebalance(), satellite_account(), split_positions(), target_value(), test_core_rebalances_only_outside_the_band(), test_satellite_account_hides_the_core_cash()

### Community 34 - "os"
Cohesion: 0.14
Nodes (3): parse_news_assessment(), blocked_name(), main()

### Community 35 - "command_center.py"
Cohesion: 0.20
Nodes (11): api_chat_history(), _agent(), chat_history(), _coo_tools(), account(), _fn(), _groq_client(), _llm_chat() (+3 more)

### Community 36 - "get_api_token"
Cohesion: 0.29
Nodes (4): get_api_token(), get_dashboard_password(), get_secret_key(), _secret()

### Community 37 - "get_config"
Cohesion: 0.38
Nodes (12): account(), buy(), holding(), pitch(), test_ai_cannot_choose_the_size(), test_bot_never_buys_the_core_symbol(), test_exhausted_risk_budget_holds(), test_panic_regime_blocks_and_crypto_needs_btc_trend() (+4 more)

### Community 38 - "chat"
Cohesion: 0.18
Nodes (7): _apply(), chat(), fallback_reply(), local_reply(), _precheck(), _propose(), _push()

### Community 39 - "update_config"
Cohesion: 0.15
Nodes (9): config_sources(), env_overrides(), _load_config(), _parse_env_value(), _read_config_file(), repo_defaults(), _save_config(), update_config() (+1 more)

### Community 40 - "_decide"
Cohesion: 0.21
Nodes (10): api_blocks(), clear_blocks(), _decide(), _default_state(), is_paused(), _load(), _save(), set_agent() (+2 more)

### Community 41 - "pipeline_diagnosis"
Cohesion: 0.22
Nodes (5): _ago(), pipeline_diagnosis(), _reason_key(), _registry_data(), _registry_view()

### Community 42 - "risk_manager"
Cohesion: 0.40
Nodes (3): build_desk_cio_prompt(), max_exposure_pct(), risk_manager()

### Community 43 - "package.json"
Cohesion: 0.29
Nodes (9): dependencies, clsx@^2.1.1, framer-motion@^14.0.0, lightweight-charts@^5.2.1, lucide@^1.52.0, clsx, framer-motion, lightweight-charts (+1 more)

### Community 44 - "_warn_throttled"
Cohesion: 0.33
Nodes (4): groq_news_llm(), _no_ai_keys(), _resolve_provider(), _warn_throttled()

### Community 45 - "describe_command"
Cohesion: 0.22
Nodes (6): propose(), describe_command(), normalize_command(), parse_command(), _rule_parse(), _segment_label()

### Community 46 - "numpy"
Cohesion: 0.16
Nodes (5): clamp_stop_pct(), hard_stop_pct(), core_returns(), mix(), stats()

### Community 47 - "drawdown_scale"
Cohesion: 0.25
Nodes (5): drawdown_scale(), regime_scale(), test_drawdown_scale(), test_missing_news_is_not_a_veto(), test_regime_scale()

### Community 48 - "universe_chunk"
Cohesion: 0.29
Nodes (4): release_memory(), universe_chunk(), universe_screener(), yf_missing()

### Community 49 - "initial_capital"
Cohesion: 0.25
Nodes (4): account_balance_for_agents(), equity_drawdown_pct(), initial_capital(), pnl_summary()

### Community 51 - "pitch_audit"
Cohesion: 0.33
Nodes (4): rejected(), _audit_close(), _audit_stages(), pitch_audit()

### Community 53 - "apply_trend_rank"
Cohesion: 0.33
Nodes (4): test_rank_is_computed_on_the_universe(), test_score_outside_trend_never_enters(), apply_trend_rank(), trend_score()

### Community 55 - "segment_matches"
Cohesion: 0.40
Nodes (3): sector_of(), _segment_impact(), segment_matches()

### Community 57 - "api_position_close"
Cohesion: 0.33
Nodes (3): api_position_close(), _cancel_open_orders(), close_position()

## Knowledge Gaps
- **18 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `QuantitativeTradingCore` connect `QuantitativeTradingCore` to `MacroSentimentAgent`, `trading_core.py`, `quant_core.py`, `quant_engine`, `MicrostructureAgent`, `PortfolioGuardianAgent`, `ChopWatchdog`, `ScoutSwarm`?**
  _High betweenness centrality (0.122) - this node is a cross-community bridge._
- **Are the 5 inferred relationships involving `log_message()` (e.g. with `api_position_de_risk()` and `background_loop()`) actually correct?**
  _`log_message()` has 5 INFERRED edges - model-reasoned connections that need verification._
- **Should `app.py` be split into smaller, more focused modules?**
  _Cohesion score 0.06836055656382335 - nodes in this community are weakly interconnected._
- **Why does `ChopWatchdog` connect `ChopWatchdog` to `MacroSentimentAgent`, `quant_core.py`, `QuantitativeTradingCore`?**
  _High betweenness centrality (0.052) - this node is a cross-community bridge._
- **Are the 7 inferred relationships involving `QuantitativeTradingCore` (e.g. with `MicrostructureAgent` and `MacroSentimentAgent`) actually correct?**
  _`QuantitativeTradingCore` has 7 INFERRED edges - model-reasoned connections that need verification._
- **Should `MacroSentimentAgent` be split into smaller, more focused modules?**
  _Cohesion score 0.07777777777777778 - nodes in this community are weakly interconnected._
- **Why does `PitchAuditRegister` connect `PitchAuditRegister` to `pitch_audit`, `os`, `trading_core.py`?**
  _High betweenness centrality (0.038) - this node is a cross-community bridge._