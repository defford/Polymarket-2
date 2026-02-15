"""
LLM prompt templates for the config builder.

Defines parameter ranges, system prompt, and the analysis prompt builder
that formats trade analysis data for the Claude API.
"""

SYSTEM_PROMPT = """You are an expert quantitative trading analyst specializing in \
short-duration (15-minute) binary option markets on Polymarket, with BTC price as the \
underlying asset. You analyze trading bot performance data and recommend optimized \
configuration parameters.

You must respond with ONLY a valid JSON object. No markdown fences, no explanation \
outside the JSON structure. The JSON must be parseable by Python's json.loads()."""


# Every configurable parameter with valid ranges and descriptions.
# Used both in the prompt (so the LLM knows constraints) and for validation.
PARAM_RANGES = {
    "signal": {
        "pm_rsi_period": {
            "min": 5, "max": 30, "type": "int",
            "desc": "RSI lookback period for Polymarket token price TA. Lower = more reactive, higher = smoother.",
        },
        "pm_rsi_oversold": {
            "min": 15.0, "max": 40.0, "type": "float",
            "desc": "RSI level below which token is considered oversold (bullish signal).",
        },
        "pm_rsi_overbought": {
            "min": 60.0, "max": 85.0, "type": "float",
            "desc": "RSI level above which token is considered overbought (bearish signal).",
        },
        "pm_macd_fast": {
            "min": 5, "max": 20, "type": "int",
            "desc": "MACD fast EMA period. Lower = faster reaction to price changes.",
        },
        "pm_macd_slow": {
            "min": 15, "max": 40, "type": "int",
            "desc": "MACD slow EMA period. Higher = smooths out noise.",
        },
        "pm_macd_signal": {
            "min": 5, "max": 15, "type": "int",
            "desc": "MACD signal line EMA period.",
        },
        "pm_momentum_lookback": {
            "min": 3, "max": 15, "type": "int",
            "desc": "Number of candles to look back for momentum calculation.",
        },
        "layer1_weight": {
            "min": 0.0, "max": 1.0, "type": "float",
            "desc": "Weight for Polymarket token TA signals. Normalized with layer2_weight.",
        },
        "layer2_weight": {
            "min": 0.0, "max": 1.0, "type": "float",
            "desc": "Weight for BTC multi-timeframe EMA signals. Normalized with layer1_weight.",
        },
        "buy_threshold": {
            "min": 0.01, "max": 0.50, "type": "float",
            "desc": "Minimum |composite_score| to trigger a trade. Higher = fewer but more selective trades.",
        },
    },
    "risk": {
        "max_position_size": {
            "min": 1.0, "max": 50.0, "type": "float",
            "desc": "Maximum USD per trade. Polymarket minimum is ~$5 for live orders.",
        },
        "max_trades_per_window": {
            "min": 1, "max": 10, "type": "int",
            "desc": "Max trades allowed per 15-minute market window.",
        },
        "max_daily_loss": {
            "min": 5.0, "max": 100.0, "type": "float",
            "desc": "Max cumulative daily loss in USD before stopping for the day.",
        },
        "min_signal_confidence": {
            "min": 0.1, "max": 0.8, "type": "float",
            "desc": "Minimum composite signal confidence (0-1) to allow a trade.",
        },
        "max_consecutive_losses": {
            "min": 1, "max": 10, "type": "int",
            "desc": "Number of consecutive losses before entering cooldown.",
        },
        "cooldown_minutes": {
            "min": 5, "max": 120, "type": "int",
            "desc": "Minutes to wait after hitting consecutive loss limit.",
        },
        "stop_trading_minutes_before_close": {
            "min": 1, "max": 10, "type": "int",
            "desc": "Stop entering new trades this many minutes before market closes.",
        },
        "max_entry_price": {
            "min": 0.50, "max": 0.95, "type": "float",
            "desc": "Max price to pay for a contract (0-1). Higher allows late entries.",
        },
    },
    "exit": {
        "trailing_stop_pct": {
            "min": 0.05, "max": 0.50, "type": "float",
            "desc": "Sell if price drops this fraction from peak. 0.20 = exit at 20% drop from high.",
        },
        "hard_stop_pct": {
            "min": 0.20, "max": 0.80, "type": "float",
            "desc": "Absolute floor: exit if price drops this fraction from entry. 0.50 = 50% loss max.",
        },
        "signal_reversal_threshold": {
            "min": 0.05, "max": 0.40, "type": "float",
            "desc": "Exit if composite signal flips this far against position.",
        },
        "tighten_at_seconds": {
            "min": 60, "max": 600, "type": "int",
            "desc": "Seconds before market close to start tightening trailing stop.",
        },
        "tightened_trailing_pct": {
            "min": 0.03, "max": 0.25, "type": "float",
            "desc": "Trailing stop % after tightening begins.",
        },
        "final_seconds": {
            "min": 15, "max": 120, "type": "int",
            "desc": "Seconds before close to enter ultra-tight zone.",
        },
        "final_trailing_pct": {
            "min": 0.02, "max": 0.15, "type": "float",
            "desc": "Ultra-tight trailing stop % in final seconds.",
        },
        "min_hold_seconds": {
            "min": 5, "max": 60, "type": "int",
            "desc": "Minimum seconds to hold before any exit (avoids noise).",
        },
        "pressure_scaling_enabled": {
            "type": "bool",
            "desc": "Whether BTC short-term pressure adjusts stop widths.",
        },
        "pressure_widen_max": {
            "min": 1.0, "max": 3.0, "type": "float",
            "desc": "Max stop multiplier when BTC pressure supports position.",
        },
        "pressure_tighten_min": {
            "min": 0.2, "max": 0.8, "type": "float",
            "desc": "Min stop multiplier when BTC pressure is against position.",
        },
        "pressure_neutral_zone": {
            "min": 0.05, "max": 0.30, "type": "float",
            "desc": "Pressure magnitude below this = no adjustment.",
        },
    },
    "trading": {
        "order_type": {
            "type": "enum", "values": ["postOnly", "limit", "market"],
            "desc": "Order type. postOnly = lowest fees, market = guaranteed fill, limit = balance.",
        },
        "price_offset": {
            "min": 0.005, "max": 0.05, "type": "float",
            "desc": "Offset from best price for limit/postOnly orders.",
        },
        "use_fok_for_strong_signals": {
            "type": "bool",
            "desc": "Use fill-or-kill for very strong signals to ensure fill.",
        },
        "strong_signal_threshold": {
            "min": 0.5, "max": 0.95, "type": "float",
            "desc": "Signal score above which FOK is used (if enabled).",
        },
        "poll_interval_seconds": {
            "min": 5, "max": 30, "type": "int",
            "desc": "How often the strategy loop checks for signals.",
        },
        "market_discovery_interval_seconds": {
            "min": 10, "max": 120, "type": "int",
            "desc": "How often to scan for new active markets.",
        },
    },
    "bayesian": {
        "enabled": {
            "type": "bool",
            "desc": "Enable Bayesian inference for signal weighting. Uses historical performance to compute P(Win|Signals).",
        },
        "rolling_window": {
            "min": 50, "max": 500, "type": "int",
            "desc": "Number of recent trades to consider for prior probability calculation.",
        },
        "min_sample_size": {
            "min": 20, "max": 100, "type": "int",
            "desc": "Minimum trades before Bayesian activates. Lower = activates sooner but less reliable.",
        },
        "confidence_threshold": {
            "min": 0.2, "max": 0.6, "type": "float",
            "desc": "Minimum posterior probability to allow trade. Higher = more selective (fewer trades).",
        },
        "smoothing_alpha": {
            "min": 0.01, "max": 1.0, "type": "float",
            "desc": "Laplace smoothing factor. Prevents zero probabilities for rare evidence combinations.",
        },
    },
}


OPTIMIZATION_GOALS = {
    "balanced": "Optimize for risk-adjusted returns. Balance win rate with total PnL. "
                "Aim for consistent profitability without excessive risk.",
    "win_rate": "Maximize win rate. Prefer conservative parameters that filter for "
                "high-probability trades. Accept fewer trades if each has a higher chance of profit.",
    "pnl": "Maximize total PnL. Tolerate lower win rate if expected value per trade is positive. "
           "More aggressive entry and larger position sizing.",
    "risk_adjusted": "Minimize drawdown and consecutive losses. Prioritize capital preservation. "
                     "Tight stops, conservative sizing, and high confidence requirements.",
}


def build_analysis_prompt(analysis: dict, goal: str, base_config: dict) -> str:
    """Build the full prompt for the LLM config generator.

    Args:
        analysis: Full analysis result dict from AnalysisEngine.
        goal: One of 'balanced', 'win_rate', 'pnl', 'risk_adjusted'.
        base_config: Current BotConfig.to_dict() to show current values.
    """
    sections = []

    # Section 1: Parameter Reference
    sections.append("## Configurable Parameters\n")
    for section_name, params in PARAM_RANGES.items():
        sections.append(f"### {section_name.title()} Config")
        current_section = base_config.get(section_name, {})
        for param, info in params.items():
            current = current_section.get(param, "?")
            if info["type"] == "bool":
                sections.append(f"- {param} (current: {current}): {info['desc']}")
            elif info["type"] == "enum":
                sections.append(
                    f"- {param} (current: \"{current}\", options: {info['values']}): {info['desc']}"
                )
            else:
                sections.append(
                    f"- {param} (current: {current}, range: {info['min']}-{info['max']}): {info['desc']}"
                )
        sections.append("")

    # Section 2: Analysis Data
    sections.append("## Analysis Data\n")

    summary = analysis.get("summary", {})
    sections.append(f"Total trades analyzed: {summary.get('total_trades_analyzed', 0)}")
    sections.append(f"Total sessions: {summary.get('total_sessions_analyzed', 0)}")
    sections.append(f"Overall win rate: {summary.get('overall_win_rate', 0):.1%}")
    sections.append(f"Overall total PnL: ${summary.get('overall_total_pnl', 0):.2f}")
    sections.append(f"Avg PnL per trade: ${summary.get('overall_avg_pnl_per_trade', 0):.4f}")
    sections.append("")

    # Signal score buckets
    buckets = analysis.get("signal_score_buckets", {})
    if buckets:
        sections.append("### Signal Score Effectiveness")
        sections.append("Score Range | Trades | Win Rate | Avg PnL")
        sections.append("--- | --- | --- | ---")
        for key, data in sorted(buckets.items()):
            sections.append(
                f"{key} | {data['count']} | {data['win_rate']:.1%} | ${data['avg_pnl']:.4f}"
            )
        sections.append("")

    # Exit reasons
    exits = analysis.get("exit_reasons", {})
    if exits:
        sections.append("### Exit Reason Breakdown")
        sections.append("Reason | Count | Avg PnL | Avg Hold (s)")
        sections.append("--- | --- | --- | ---")
        for reason, data in exits.items():
            sections.append(
                f"{reason} | {data['count']} | ${data['avg_pnl']:.4f} | {data['avg_hold_seconds']:.0f}"
            )
        sections.append("")

    # Threshold analysis
    thresholds = analysis.get("threshold_analysis", {})
    if thresholds:
        sections.append("### Buy Threshold Effectiveness")
        sections.append("Threshold | Trades Above | Win Rate | Avg PnL")
        sections.append("--- | --- | --- | ---")
        for thresh, data in sorted(thresholds.items()):
            sections.append(
                f"{thresh} | {data['trades_above']} | {data['win_rate_above']:.1%} | ${data['avg_pnl_above']:.4f}"
            )
        sections.append("")

    # Layer weight analysis
    layers = analysis.get("layer_weight_analysis", {})
    if layers:
        sections.append("### Layer Weight Analysis")
        l1_corr = layers.get("l1_direction_vs_pnl_correlation")
        l2_corr = layers.get("l2_direction_vs_pnl_correlation")
        if l1_corr is not None:
            sections.append(f"Layer1 direction vs PnL correlation: {l1_corr:.4f}")
        if l2_corr is not None:
            sections.append(f"Layer2 direction vs PnL correlation: {l2_corr:.4f}")
        agree = layers.get("both_agree_trades", {})
        dis = layers.get("layers_disagree_trades", {})
        if agree.get("count"):
            sections.append(
                f"Both layers agree: {agree['count']} trades, {agree['win_rate']:.1%} win rate, "
                f"${agree['avg_pnl']:.4f} avg PnL"
            )
        if dis.get("count"):
            sections.append(
                f"Layers disagree: {dis['count']} trades, {dis['win_rate']:.1%} win rate, "
                f"${dis['avg_pnl']:.4f} avg PnL"
            )
        sections.append("")

    # Position sizing
    sizing = analysis.get("position_sizing", {})
    if sizing:
        sections.append("### Position Sizing")
        sections.append("Size Range | Trades | Avg PnL | PnL per $")
        sections.append("--- | --- | --- | ---")
        for label, data in sizing.items():
            sections.append(
                f"{label} | {data['count']} | ${data['avg_pnl']:.4f} | ${data['pnl_per_dollar']:.4f}"
            )
        sections.append("")

    # Time patterns
    time_data = analysis.get("time_patterns", {})
    if time_data:
        sections.append("### Time-of-Day Patterns")
        best = time_data.get("best_hours", [])
        worst = time_data.get("worst_hours", [])
        if best:
            sections.append(f"Best hours (UTC): {', '.join(str(h) for h in best)}")
        if worst:
            sections.append(f"Worst hours (UTC): {', '.join(str(h) for h in worst)}")
        hourly = time_data.get("hourly", {})
        if hourly:
            sections.append("Hour | Trades | Win Rate | Avg PnL")
            sections.append("--- | --- | --- | ---")
            for hour, data in sorted(hourly.items()):
                sections.append(
                    f"{hour} | {data['count']} | {data['win_rate']:.1%} | ${data['avg_pnl']:.4f}"
                )
        sections.append("")

    # Hold duration
    hold = analysis.get("hold_duration", {})
    duration_buckets = hold.get("duration_buckets", {})
    if duration_buckets:
        sections.append("### Hold Duration vs PnL")
        sections.append("Duration | Trades | Win Rate | Avg PnL")
        sections.append("--- | --- | --- | ---")
        for label, data in duration_buckets.items():
            sections.append(
                f"{label} | {data['count']} | {data['win_rate']:.1%} | ${data['avg_pnl']:.4f}"
            )
        sections.append("")

    # Drawdown patterns
    dd = analysis.get("drawdown_patterns", {})
    if dd:
        sections.append("### Drawdown Patterns")
        rec = dd.get("recovered", {})
        nrec = dd.get("not_recovered", {})
        if rec.get("count"):
            sections.append(
                f"Recovered from drawdown: {rec['count']} trades, "
                f"avg drawdown {rec['avg_max_drawdown']:.1%}, avg PnL ${rec['avg_final_pnl']:.4f}"
            )
        if nrec.get("count"):
            sections.append(
                f"Did NOT recover: {nrec['count']} trades, "
                f"avg drawdown {nrec['avg_max_drawdown']:.1%}, avg PnL ${nrec['avg_final_pnl']:.4f}"
            )
        thresh_data = dd.get("drawdown_threshold_analysis", {})
        if thresh_data:
            for thresh, data in sorted(thresh_data.items()):
                sections.append(
                    f"Drawdown >= {float(thresh):.0%}: {data['total']} trades, "
                    f"{data['recovery_rate']:.1%} recovered"
                )
        sections.append("")

    # BTC pressure
    btc = analysis.get("btc_pressure", {})
    if btc:
        sections.append("### BTC Pressure at Exit")
        for key in ["btc_positive_at_exit", "btc_negative_at_exit", "btc_neutral_at_exit"]:
            data = btc.get(key, {})
            if data.get("count"):
                label = key.replace("btc_", "").replace("_at_exit", "").replace("_", " ").title()
                sections.append(f"{label}: {data['count']} trades, avg PnL ${data['avg_pnl']:.4f}")
        sections.append("")

    # Consecutive losses
    consec = analysis.get("consecutive_losses", {})
    if consec:
        sections.append("### Consecutive Loss Patterns")
        streaks = consec.get("streak_distribution", {})
        if streaks:
            sections.append(f"Loss streak distribution: {streaks}")
        recovery = consec.get("recovery_after_streak", {})
        if recovery:
            for length, data in sorted(recovery.items()):
                sections.append(
                    f"After {length} consecutive losses: "
                    f"next trade wins {data['next_trade_win_rate']:.1%} of the time "
                    f"({data['total_occurrences']} occurrences)"
                )
        sections.append("")

    # Per-bot comparison
    per_bot = analysis.get("per_bot", {})
    if per_bot:
        sections.append("### Per-Bot Comparison")
        sections.append("Bot | Trades | Win Rate | Total PnL | Avg PnL")
        sections.append("--- | --- | --- | --- | ---")
        for bot_id, data in per_bot.items():
            sections.append(
                f"{data['name']} | {data['total_trades']} | {data['win_rate']:.1%} | "
                f"${data['total_pnl']:.2f} | ${data['avg_pnl']:.4f}"
            )
        sections.append("")

    # Bayesian analysis
    bayesian = analysis.get("bayesian", {})
    if bayesian:
        sections.append("### Bayesian Analysis")
        
        # Evidence combinations
        evidence = bayesian.get("evidence_combinations", {})
        if evidence:
            sections.append("#### Evidence Combinations")
            sections.append("Evidence | Trades | Win Rate | Avg PnL")
            sections.append("--- | --- | --- | ---")
            for key, data in list(evidence.items())[:10]:
                sections.append(
                    f"{key} | {data['count']} | {data['win_rate']:.1%} | ${data['avg_pnl']:.4f}"
                )
            sections.append("")
        
        # Posterior buckets
        posterior = bayesian.get("posterior_buckets", {})
        if posterior:
            sections.append("#### Posterior Distribution")
            sections.append("Posterior Range | Trades | Win Rate | Avg PnL")
            sections.append("--- | --- | --- | ---")
            for key, data in sorted(posterior.items()):
                sections.append(
                    f"{key} | {data['count']} | {data['win_rate']:.1%} | ${data['avg_pnl']:.4f}"
                )
            sections.append("")
        
        # Gate behavior
        gate_passed = bayesian.get("gate_passed", {})
        gate_blocked = bayesian.get("gate_blocked", {})
        if gate_passed.get("count") or gate_blocked.get("count"):
            sections.append("#### Confidence Gate Behavior")
            if gate_passed.get("count"):
                sections.append(
                    f"Passed gate: {gate_passed['count']} trades, {gate_passed['win_rate']:.1%} win rate, "
                    f"${gate_passed['avg_pnl']:.4f} avg PnL"
                )
            if gate_blocked.get("count"):
                sections.append(
                    f"Blocked by gate: {gate_blocked['count']} trades, {gate_blocked['potential_win_rate']:.1%} would-have-won rate, "
                    f"${gate_blocked['potential_avg_pnl']:.4f} potential avg PnL"
                )
            sections.append("")
        
        # Fallback vs active mode
        fallback = bayesian.get("fallback_mode", {})
        active = bayesian.get("active_mode", {})
        if fallback.get("count") or active.get("count"):
            sections.append("#### Bayesian Mode")
            if fallback.get("count"):
                sections.append(
                    f"Fallback (< min trades): {fallback['count']} trades, {fallback['win_rate']:.1%} win rate"
                )
            if active.get("count"):
                sections.append(
                    f"Active Bayesian: {active['count']} trades, {active['win_rate']:.1%} win rate"
                )
            sections.append("")
        
        # Correlation
        corr = bayesian.get("posterior_vs_pnl_correlation")
        if corr is not None:
            sections.append(f"Posterior vs PnL correlation: {corr:.4f}")
            sections.append("")

    # Section 3: Optimization Goal
    goal_desc = OPTIMIZATION_GOALS.get(goal, OPTIMIZATION_GOALS["balanced"])
    sections.append(f"## Optimization Goal: {goal}\n")
    sections.append(goal_desc)
    sections.append("")

    # Section 4: Response Format
    sections.append("## Required Response Format\n")
    sections.append("""Respond with EXACTLY this JSON structure (no markdown, no code fences):
{
    "config": {
        "signal": { <all SignalConfig fields with your recommended values> },
        "risk": { <all RiskConfig fields with your recommended values> },
        "exit": { <all ExitConfig fields with your recommended values> },
        "trading": { <all TradingConfig fields with your recommended values> },
        "bayesian": { <all BayesianConfig fields with your recommended values> },
        "mode": "dry_run"
    },
    "reasoning": "2-3 paragraphs explaining what you changed and why, referencing specific data from the analysis.",
    "optimization_focus": "<the goal you optimized for>",
    "suggested_name": "A short descriptive name like 'Conservative Scalper' or 'Aggressive Momentum'",
    "confidence": "high|medium|low",
    "key_changes": [
        "param_name: old_value -> new_value (reason from analysis data)",
        ...
    ]
}""")

    return "\n".join(sections)
