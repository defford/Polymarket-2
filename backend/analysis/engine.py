"""
AnalysisEngine — computes comprehensive metrics from all trade sessions.

Loads all filled trades in one query, parses trade_log_data JSON,
and computes 12 metric categories in a single pass.
"""

import json
import logging
from collections import defaultdict
from datetime import datetime
from typing import Optional

import database as db

logger = logging.getLogger(__name__)

MIN_TRADES_FOR_ANALYSIS = 10


class AnalysisEngine:
    """Analyzes all trade sessions across the swarm."""

    def run_analysis(
        self,
        bot_ids: Optional[list[int]] = None,
        since: Optional[str] = None,
    ) -> dict:
        """Run full analysis across all bots/sessions.

        Returns a dict with 12 metric categories + summary.
        """
        # Load all filled trades with log data
        raw = db.get_all_filled_trades_with_log_data(bot_ids=bot_ids, since=since)

        trades = []
        for trade, log_json in raw:
            log_data = None
            if log_json:
                try:
                    log_data = json.loads(log_json)
                except (json.JSONDecodeError, TypeError):
                    pass
            trades.append({"trade": trade, "log_data": log_data})

        # Count sessions
        session_ids = set()
        for t in trades:
            if t["trade"].session_id:
                session_ids.add(t["trade"].session_id)

        total_trades = len(trades)
        trades_with_log = [t for t in trades if t["log_data"]]

        if total_trades < MIN_TRADES_FOR_ANALYSIS:
            return {
                "warning": f"Only {total_trades} filled trades found (minimum {MIN_TRADES_FOR_ANALYSIS}). Analysis may be unreliable.",
                "summary": self._compute_summary(trades, session_ids),
                "signal_score_buckets": {},
                "exit_reasons": {},
                "threshold_analysis": {},
                "layer_weight_analysis": {},
                "position_sizing": {},
                "time_patterns": {},
                "hold_duration": {},
                "drawdown_patterns": {},
                "btc_pressure": {},
                "consecutive_losses": {},
                "per_bot": {},
                "trade_count": total_trades,
                "session_count": len(session_ids),
            }

        return {
            "summary": self._compute_summary(trades, session_ids),
            "signal_score_buckets": self._signal_score_effectiveness(trades),
            "exit_reasons": self._exit_reason_analysis(trades_with_log),
            "threshold_analysis": self._threshold_effectiveness(trades),
            "layer_weight_analysis": self._layer_weight_correlation(trades_with_log),
            "position_sizing": self._position_sizing_analysis(trades),
            "time_patterns": self._time_of_day_patterns(trades),
            "hold_duration": self._hold_duration_analysis(trades_with_log),
            "drawdown_patterns": self._drawdown_analysis(trades_with_log),
            "btc_pressure": self._btc_pressure_analysis(trades_with_log),
            "consecutive_losses": self._consecutive_loss_analysis(trades),
            "per_bot": self._per_bot_comparison(trades),
            "slippage": self._slippage_analysis(trades_with_log),
            "mae_mfe": self._mae_mfe_analysis(trades_with_log),
            "fill_rate": self._fill_rate_analysis(trades_with_log),
            "orderbook": self._orderbook_analysis(trades_with_log),
            "bayesian": self._bayesian_analysis(trades_with_log),
            "survival": self._survival_analysis(trades_with_log),
            "trade_count": total_trades,
            "session_count": len(session_ids),
        }

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def _compute_summary(self, trades: list[dict], session_ids: set) -> dict:
        total = len(trades)
        if total == 0:
            return {
                "total_trades_analyzed": 0,
                "total_sessions_analyzed": 0,
                "total_bots": 0,
                "date_range": None,
                "overall_win_rate": 0,
                "overall_total_pnl": 0,
                "overall_avg_pnl_per_trade": 0,
            }

        wins = sum(1 for t in trades if (t["trade"].pnl or 0) > 0)
        total_pnl = sum(t["trade"].pnl or 0 for t in trades)
        bot_ids = set(t["trade"].bot_id for t in trades if t["trade"].bot_id)
        timestamps = [t["trade"].timestamp for t in trades]

        return {
            "total_trades_analyzed": total,
            "total_sessions_analyzed": len(session_ids),
            "total_bots": len(bot_ids),
            "date_range": {
                "from": min(timestamps).isoformat(),
                "to": max(timestamps).isoformat(),
            },
            "overall_win_rate": round(wins / total, 4) if total else 0,
            "overall_total_pnl": round(total_pnl, 4),
            "overall_avg_pnl_per_trade": round(total_pnl / total, 4) if total else 0,
        }

    # ------------------------------------------------------------------
    # 1. Signal Score Effectiveness
    # ------------------------------------------------------------------

    def _signal_score_effectiveness(self, trades: list[dict]) -> dict:
        buckets = defaultdict(lambda: {"count": 0, "wins": 0, "losses": 0, "total_pnl": 0.0})

        for t in trades:
            score = abs(t["trade"].signal_score or 0)
            pnl = t["trade"].pnl or 0
            bucket_idx = min(int(score * 10), 9)  # 0-9
            key = f"{bucket_idx / 10:.2f}-{(bucket_idx + 1) / 10:.2f}"
            buckets[key]["count"] += 1
            buckets[key]["total_pnl"] += pnl
            if pnl > 0:
                buckets[key]["wins"] += 1
            elif pnl < 0:
                buckets[key]["losses"] += 1

        result = {}
        for key in sorted(buckets.keys()):
            b = buckets[key]
            b["win_rate"] = round(b["wins"] / b["count"], 4) if b["count"] else 0
            b["avg_pnl"] = round(b["total_pnl"] / b["count"], 4) if b["count"] else 0
            b["total_pnl"] = round(b["total_pnl"], 4)
            result[key] = b

        return result

    # ------------------------------------------------------------------
    # 2. Exit Reason Analysis
    # ------------------------------------------------------------------

    def _exit_reason_analysis(self, trades: list[dict]) -> dict:
        reasons = defaultdict(lambda: {"count": 0, "total_pnl": 0.0, "total_hold_seconds": 0.0})

        for t in trades:
            ld = t["log_data"]
            reason = ld.get("exit_reason", "unknown")
            pnl = t["trade"].pnl or 0
            hold = ld.get("position_held_duration_seconds", 0) or 0
            reasons[reason]["count"] += 1
            reasons[reason]["total_pnl"] += pnl
            reasons[reason]["total_hold_seconds"] += hold

        result = {}
        for reason, data in sorted(reasons.items()):
            c = data["count"]
            result[reason] = {
                "count": c,
                "avg_pnl": round(data["total_pnl"] / c, 4) if c else 0,
                "total_pnl": round(data["total_pnl"], 4),
                "avg_hold_seconds": round(data["total_hold_seconds"] / c, 1) if c else 0,
            }
        return result

    # ------------------------------------------------------------------
    # 3. Buy Threshold Effectiveness
    # ------------------------------------------------------------------

    def _threshold_effectiveness(self, trades: list[dict]) -> dict:
        thresholds = [0.05, 0.08, 0.10, 0.12, 0.15, 0.20, 0.25, 0.30]
        result = {}

        for threshold in thresholds:
            above = [t for t in trades if abs(t["trade"].signal_score or 0) >= threshold]
            if not above:
                result[str(threshold)] = {"trades_above": 0, "win_rate_above": 0, "avg_pnl_above": 0}
                continue
            wins = sum(1 for t in above if (t["trade"].pnl or 0) > 0)
            total_pnl = sum(t["trade"].pnl or 0 for t in above)
            result[str(threshold)] = {
                "trades_above": len(above),
                "win_rate_above": round(wins / len(above), 4),
                "avg_pnl_above": round(total_pnl / len(above), 4),
            }

        return result

    # ------------------------------------------------------------------
    # 4. Layer Weight Correlation
    # ------------------------------------------------------------------

    def _layer_weight_correlation(self, trades: list[dict]) -> dict:
        l1_directions = []
        l2_directions = []
        pnls = []
        both_agree = {"count": 0, "wins": 0, "total_pnl": 0.0}
        disagree = {"count": 0, "wins": 0, "total_pnl": 0.0}
        l1_strong = {"count": 0, "total_pnl": 0.0}
        l2_strong = {"count": 0, "total_pnl": 0.0}

        for t in trades:
            ld = t["log_data"]
            buy_state = ld.get("buy_state", {})
            signal = buy_state.get("signal", {})
            l1 = signal.get("layer1", {})
            l2 = signal.get("layer2", {})
            l1_dir = l1.get("direction", 0)
            l2_dir = l2.get("direction", 0)
            pnl = t["trade"].pnl or 0

            if l1_dir == 0 and l2_dir == 0:
                continue

            l1_directions.append(l1_dir)
            l2_directions.append(l2_dir)
            pnls.append(pnl)

            # Agreement
            if (l1_dir > 0 and l2_dir > 0) or (l1_dir < 0 and l2_dir < 0):
                both_agree["count"] += 1
                both_agree["total_pnl"] += pnl
                if pnl > 0:
                    both_agree["wins"] += 1
            else:
                disagree["count"] += 1
                disagree["total_pnl"] += pnl
                if pnl > 0:
                    disagree["wins"] += 1

            # Strong signals
            if abs(l1_dir) > 0.5:
                l1_strong["count"] += 1
                l1_strong["total_pnl"] += pnl
            if abs(l2_dir) > 0.5:
                l2_strong["count"] += 1
                l2_strong["total_pnl"] += pnl

        # Simple correlation (avoid numpy dependency)
        l1_corr = self._pearson(l1_directions, pnls)
        l2_corr = self._pearson(l2_directions, pnls)

        return {
            "l1_direction_vs_pnl_correlation": round(l1_corr, 4) if l1_corr is not None else None,
            "l2_direction_vs_pnl_correlation": round(l2_corr, 4) if l2_corr is not None else None,
            "l1_strong_trades": {
                "count": l1_strong["count"],
                "avg_pnl": round(l1_strong["total_pnl"] / l1_strong["count"], 4) if l1_strong["count"] else 0,
            },
            "l2_strong_trades": {
                "count": l2_strong["count"],
                "avg_pnl": round(l2_strong["total_pnl"] / l2_strong["count"], 4) if l2_strong["count"] else 0,
            },
            "both_agree_trades": {
                "count": both_agree["count"],
                "win_rate": round(both_agree["wins"] / both_agree["count"], 4) if both_agree["count"] else 0,
                "avg_pnl": round(both_agree["total_pnl"] / both_agree["count"], 4) if both_agree["count"] else 0,
            },
            "layers_disagree_trades": {
                "count": disagree["count"],
                "win_rate": round(disagree["wins"] / disagree["count"], 4) if disagree["count"] else 0,
                "avg_pnl": round(disagree["total_pnl"] / disagree["count"], 4) if disagree["count"] else 0,
            },
        }

    # ------------------------------------------------------------------
    # 5. Position Sizing Analysis
    # ------------------------------------------------------------------

    def _position_sizing_analysis(self, trades: list[dict]) -> dict:
        size_ranges = [(0, 3, "0-3"), (3, 5, "3-5"), (5, 10, "5-10"), (10, float("inf"), "10+")]
        buckets = {label: {"count": 0, "total_pnl": 0.0, "total_cost": 0.0} for _, _, label in size_ranges}

        for t in trades:
            cost = t["trade"].cost or 0
            pnl = t["trade"].pnl or 0
            for lo, hi, label in size_ranges:
                if lo <= cost < hi:
                    buckets[label]["count"] += 1
                    buckets[label]["total_pnl"] += pnl
                    buckets[label]["total_cost"] += cost
                    break

        result = {}
        for label, data in buckets.items():
            c = data["count"]
            result[label] = {
                "count": c,
                "avg_pnl": round(data["total_pnl"] / c, 4) if c else 0,
                "pnl_per_dollar": round(data["total_pnl"] / data["total_cost"], 4) if data["total_cost"] else 0,
            }
        return result

    # ------------------------------------------------------------------
    # 6. Time-of-Day Patterns
    # ------------------------------------------------------------------

    def _time_of_day_patterns(self, trades: list[dict]) -> dict:
        hourly = defaultdict(lambda: {"count": 0, "wins": 0, "total_pnl": 0.0})

        for t in trades:
            hour = t["trade"].timestamp.hour
            pnl = t["trade"].pnl or 0
            key = f"{hour:02d}"
            hourly[key]["count"] += 1
            hourly[key]["total_pnl"] += pnl
            if pnl > 0:
                hourly[key]["wins"] += 1

        result = {}
        for key in sorted(hourly.keys()):
            h = hourly[key]
            c = h["count"]
            result[key] = {
                "count": c,
                "win_rate": round(h["wins"] / c, 4) if c else 0,
                "avg_pnl": round(h["total_pnl"] / c, 4) if c else 0,
            }

        # Best and worst hours (by avg PnL, minimum 3 trades)
        qualified = {k: v for k, v in result.items() if v["count"] >= 3}
        best = sorted(qualified.keys(), key=lambda k: qualified[k]["avg_pnl"], reverse=True)[:3]
        worst = sorted(qualified.keys(), key=lambda k: qualified[k]["avg_pnl"])[:3]

        return {"hourly": result, "best_hours": best, "worst_hours": worst}

    # ------------------------------------------------------------------
    # 7. Hold Duration vs PnL
    # ------------------------------------------------------------------

    def _hold_duration_analysis(self, trades: list[dict]) -> dict:
        duration_ranges = [
            (0, 60, "0-60s"),
            (60, 120, "60-120s"),
            (120, 300, "120-300s"),
            (300, 600, "300-600s"),
            (600, float("inf"), "600s+"),
        ]
        buckets = {label: {"count": 0, "wins": 0, "total_pnl": 0.0} for _, _, label in duration_ranges}

        for t in trades:
            dur = t["log_data"].get("position_held_duration_seconds", 0) or 0
            pnl = t["trade"].pnl or 0
            for lo, hi, label in duration_ranges:
                if lo <= dur < hi:
                    buckets[label]["count"] += 1
                    buckets[label]["total_pnl"] += pnl
                    if pnl > 0:
                        buckets[label]["wins"] += 1
                    break

        result = {}
        for label in [r[2] for r in duration_ranges]:
            b = buckets[label]
            c = b["count"]
            result[label] = {
                "count": c,
                "win_rate": round(b["wins"] / c, 4) if c else 0,
                "avg_pnl": round(b["total_pnl"] / c, 4) if c else 0,
            }
        return {"duration_buckets": result}

    # ------------------------------------------------------------------
    # 8. Drawdown Patterns
    # ------------------------------------------------------------------

    def _drawdown_analysis(self, trades: list[dict]) -> dict:
        recovered = {"count": 0, "total_drawdown": 0.0, "total_pnl": 0.0}
        not_recovered = {"count": 0, "total_drawdown": 0.0, "total_pnl": 0.0}
        threshold_recovery = defaultdict(lambda: {"total": 0, "recovered": 0})

        for t in trades:
            ld = t["log_data"]
            drawdown = ld.get("drawdown_from_peak", 0) or 0
            pnl = t["trade"].pnl or 0

            if drawdown > 0.01:  # Had meaningful drawdown
                if pnl > 0:
                    recovered["count"] += 1
                    recovered["total_drawdown"] += drawdown
                    recovered["total_pnl"] += pnl
                else:
                    not_recovered["count"] += 1
                    not_recovered["total_drawdown"] += drawdown
                    not_recovered["total_pnl"] += pnl

                for thresh in [0.05, 0.10, 0.15, 0.20, 0.30]:
                    if drawdown >= thresh:
                        threshold_recovery[str(thresh)]["total"] += 1
                        if pnl > 0:
                            threshold_recovery[str(thresh)]["recovered"] += 1

        thresh_result = {}
        for thresh, data in sorted(threshold_recovery.items()):
            thresh_result[thresh] = {
                "total": data["total"],
                "recovery_rate": round(data["recovered"] / data["total"], 4) if data["total"] else 0,
            }

        return {
            "recovered": {
                "count": recovered["count"],
                "avg_max_drawdown": round(recovered["total_drawdown"] / recovered["count"], 4) if recovered["count"] else 0,
                "avg_final_pnl": round(recovered["total_pnl"] / recovered["count"], 4) if recovered["count"] else 0,
            },
            "not_recovered": {
                "count": not_recovered["count"],
                "avg_max_drawdown": round(not_recovered["total_drawdown"] / not_recovered["count"], 4) if not_recovered["count"] else 0,
                "avg_final_pnl": round(not_recovered["total_pnl"] / not_recovered["count"], 4) if not_recovered["count"] else 0,
            },
            "drawdown_threshold_analysis": thresh_result,
        }

    # ------------------------------------------------------------------
    # 9. BTC Pressure Analysis
    # ------------------------------------------------------------------

    def _btc_pressure_analysis(self, trades: list[dict]) -> dict:
        positive = {"count": 0, "total_pnl": 0.0}
        negative = {"count": 0, "total_pnl": 0.0}
        neutral = {"count": 0, "total_pnl": 0.0}

        for t in trades:
            ld = t["log_data"]
            sell_state = ld.get("sell_state", {})
            signal = sell_state.get("signal", {})
            l2 = signal.get("layer2", {})
            l2_dir = l2.get("direction", 0)
            pnl = t["trade"].pnl or 0

            if l2_dir > 0.15:
                positive["count"] += 1
                positive["total_pnl"] += pnl
            elif l2_dir < -0.15:
                negative["count"] += 1
                negative["total_pnl"] += pnl
            else:
                neutral["count"] += 1
                neutral["total_pnl"] += pnl

        return {
            "btc_positive_at_exit": {
                "count": positive["count"],
                "avg_pnl": round(positive["total_pnl"] / positive["count"], 4) if positive["count"] else 0,
            },
            "btc_negative_at_exit": {
                "count": negative["count"],
                "avg_pnl": round(negative["total_pnl"] / negative["count"], 4) if negative["count"] else 0,
            },
            "btc_neutral_at_exit": {
                "count": neutral["count"],
                "avg_pnl": round(neutral["total_pnl"] / neutral["count"], 4) if neutral["count"] else 0,
            },
        }

    # ------------------------------------------------------------------
    # 10. Consecutive Loss Patterns
    # ------------------------------------------------------------------

    def _consecutive_loss_analysis(self, trades: list[dict]) -> dict:
        # Group trades by bot, then iterate chronologically
        by_bot = defaultdict(list)
        for t in trades:
            bot_id = t["trade"].bot_id or 0
            by_bot[bot_id].append(t)

        streaks = defaultdict(int)  # streak_length -> count
        recovery = defaultdict(lambda: {"total": 0, "next_win": 0})

        for bot_id, bot_trades in by_bot.items():
            bot_trades.sort(key=lambda x: x["trade"].timestamp)
            current_streak = 0
            for i, t in enumerate(bot_trades):
                pnl = t["trade"].pnl or 0
                if pnl < 0:
                    current_streak += 1
                else:
                    if current_streak > 0:
                        streaks[current_streak] += 1
                        recovery[current_streak]["total"] += 1
                        if pnl > 0:
                            recovery[current_streak]["next_win"] += 1
                    current_streak = 0
            # Trailing streak
            if current_streak > 0:
                streaks[current_streak] += 1

        streak_dist = {str(k): v for k, v in sorted(streaks.items())}
        recovery_rates = {}
        for streak_len, data in sorted(recovery.items()):
            recovery_rates[str(streak_len)] = {
                "total_occurrences": data["total"],
                "next_trade_win_rate": round(data["next_win"] / data["total"], 4) if data["total"] else 0,
            }

        return {
            "streak_distribution": streak_dist,
            "recovery_after_streak": recovery_rates,
        }

    # ------------------------------------------------------------------
    # 11. Per-Bot Comparison
    # ------------------------------------------------------------------

    def _per_bot_comparison(self, trades: list[dict]) -> dict:
        by_bot = defaultdict(lambda: {"trades": 0, "wins": 0, "total_pnl": 0.0, "total_fees": 0.0})

        for t in trades:
            bot_id = str(t["trade"].bot_id or "unknown")
            pnl = t["trade"].pnl or 0
            by_bot[bot_id]["trades"] += 1
            by_bot[bot_id]["total_pnl"] += pnl
            by_bot[bot_id]["total_fees"] += t["trade"].fees or 0
            if pnl > 0:
                by_bot[bot_id]["wins"] += 1

        # Enrich with bot names from DB
        all_bots = db.get_all_bots()
        bot_names = {str(b.id): b.name for b in all_bots}
        bot_configs = {}
        for b in all_bots:
            try:
                bot_configs[str(b.id)] = json.loads(b.config_json)
            except (json.JSONDecodeError, TypeError):
                bot_configs[str(b.id)] = {}

        result = {}
        for bot_id, data in by_bot.items():
            c = data["trades"]
            result[bot_id] = {
                "name": bot_names.get(bot_id, f"Bot {bot_id}"),
                "total_trades": c,
                "win_rate": round(data["wins"] / c, 4) if c else 0,
                "total_pnl": round(data["total_pnl"], 4),
                "avg_pnl": round(data["total_pnl"] / c, 4) if c else 0,
                "total_fees": round(data["total_fees"], 4),
                "config": bot_configs.get(bot_id, {}),
            }
        return result

    # ------------------------------------------------------------------
    # 12. Slippage Analysis
    # ------------------------------------------------------------------

    def _slippage_analysis(self, trades: list[dict]) -> dict:
        by_order_type = defaultdict(lambda: {
            "count": 0, "total_entry_slippage_bps": 0.0, "total_exit_slippage_bps": 0.0,
            "total_slippage_cost": 0.0, "total_pnl": 0.0,
        })

        has_data = False
        for t in trades:
            ld = t["log_data"]
            entry_slip = ld.get("entry_slippage")
            exit_slip = ld.get("exit_slippage")
            if not entry_slip and not exit_slip:
                continue

            has_data = True
            order_type = (entry_slip or {}).get("order_type", "unknown")
            pnl = t["trade"].pnl or 0
            b = by_order_type[order_type]
            b["count"] += 1
            b["total_pnl"] += pnl

            if entry_slip:
                b["total_entry_slippage_bps"] += entry_slip.get("slippage_bps", 0)
                # Estimate cost: slippage_bps * position_cost / 10000
                cost = t["trade"].cost or 0
                b["total_slippage_cost"] += abs(entry_slip.get("slippage_bps", 0)) * cost / 10000
            if exit_slip:
                b["total_exit_slippage_bps"] += exit_slip.get("slippage_bps", 0)

        if not has_data:
            return {}

        result = {}
        total_cost = 0.0
        total_count = 0
        for ot, data in sorted(by_order_type.items()):
            c = data["count"]
            total_cost += data["total_slippage_cost"]
            total_count += c
            result[ot] = {
                "count": c,
                "avg_entry_slippage_bps": round(data["total_entry_slippage_bps"] / c, 2) if c else 0,
                "avg_exit_slippage_bps": round(data["total_exit_slippage_bps"] / c, 2) if c else 0,
                "total_slippage_cost": round(data["total_slippage_cost"], 4),
                "avg_pnl": round(data["total_pnl"] / c, 4) if c else 0,
            }

        return {
            "by_order_type": result,
            "total_slippage_cost": round(total_cost, 4),
            "total_trades_with_data": total_count,
        }

    # ------------------------------------------------------------------
    # 13. MAE/MFE Analysis
    # ------------------------------------------------------------------

    def _mae_mfe_analysis(self, trades: list[dict]) -> dict:
        winners = {"count": 0, "total_mae": 0.0, "total_mfe": 0.0, "total_capture": 0.0, "total_missed": 0.0}
        losers = {"count": 0, "total_mae": 0.0, "total_mfe": 0.0}
        mae_buckets = defaultdict(lambda: {"count": 0, "recovered": 0})

        has_data = False
        for t in trades:
            ld = t["log_data"]
            mae_mfe = ld.get("mae_mfe")
            if not mae_mfe:
                continue

            has_data = True
            pnl = t["trade"].pnl or 0
            mae_pct = mae_mfe.get("mae_pct", 0) or 0
            mfe_pct = mae_mfe.get("mfe_pct", 0) or 0
            capture = mae_mfe.get("capture_ratio", 0) or 0
            actual_return = mae_mfe.get("actual_return_pct", 0) or 0

            if pnl > 0:
                winners["count"] += 1
                winners["total_mae"] += mae_pct
                winners["total_mfe"] += mfe_pct
                winners["total_capture"] += capture
                winners["total_missed"] += max(0, mfe_pct - actual_return)
            else:
                losers["count"] += 1
                losers["total_mae"] += mae_pct
                losers["total_mfe"] += mfe_pct

            # MAE recovery buckets (what % of trades that dipped X% recovered to profit?)
            for thresh in [0.01, 0.02, 0.05, 0.10, 0.15]:
                if mae_pct >= thresh:
                    key = f"{thresh:.0%}"
                    mae_buckets[key]["count"] += 1
                    if pnl > 0:
                        mae_buckets[key]["recovered"] += 1

        if not has_data:
            return {}

        wc = winners["count"]
        lc = losers["count"]

        recovery_by_mae = {}
        for key in sorted(mae_buckets.keys()):
            b = mae_buckets[key]
            recovery_by_mae[key] = {
                "total": b["count"],
                "recovery_rate": round(b["recovered"] / b["count"], 4) if b["count"] else 0,
            }

        return {
            "winners": {
                "count": wc,
                "avg_mae_pct": round(winners["total_mae"] / wc, 6) if wc else 0,
                "avg_mfe_pct": round(winners["total_mfe"] / wc, 6) if wc else 0,
                "avg_capture_ratio": round(winners["total_capture"] / wc, 4) if wc else 0,
                "avg_missed_profit_pct": round(winners["total_missed"] / wc, 6) if wc else 0,
            },
            "losers": {
                "count": lc,
                "avg_mae_pct": round(losers["total_mae"] / lc, 6) if lc else 0,
                "avg_mfe_pct": round(losers["total_mfe"] / lc, 6) if lc else 0,
            },
            "recovery_by_mae_threshold": recovery_by_mae,
        }

    # ------------------------------------------------------------------
    # 14. Fill Rate Analysis
    # ------------------------------------------------------------------

    def _fill_rate_analysis(self, trades: list[dict]) -> dict:
        by_type = defaultdict(lambda: {
            "total": 0, "filled": 0, "cancelled": 0, "rejected": 0,
            "total_time": 0.0, "total_retries": 0, "total_pnl": 0.0,
        })

        has_data = False
        for t in trades:
            ld = t["log_data"]
            fi = ld.get("fill_info")
            if not fi:
                continue

            has_data = True
            ot = fi.get("order_type", "unknown")
            status = fi.get("fill_status", "unknown")
            pnl = t["trade"].pnl or 0
            b = by_type[ot]
            b["total"] += 1
            b["total_pnl"] += pnl
            b["total_time"] += fi.get("time_to_fill_seconds", 0) or 0
            b["total_retries"] += fi.get("retries", 0) or 0

            if status == "filled":
                b["filled"] += 1
            elif status == "cancelled":
                b["cancelled"] += 1
            elif status in ("rejected", "unverified"):
                b["rejected"] += 1

        if not has_data:
            return {}

        result = {}
        for ot, data in sorted(by_type.items()):
            c = data["total"]
            result[ot] = {
                "total_attempts": c,
                "fill_rate": round(data["filled"] / c, 4) if c else 0,
                "cancelled": data["cancelled"],
                "rejected": data["rejected"],
                "avg_time_to_fill": round(data["total_time"] / c, 2) if c else 0,
                "avg_retries": round(data["total_retries"] / c, 1) if c else 0,
                "avg_pnl": round(data["total_pnl"] / c, 4) if c else 0,
            }

        # FOK vs non-FOK comparison
        fok_trades = [t for t in trades if t["log_data"].get("fill_info", {}).get("was_fok")]
        non_fok = [t for t in trades if t["log_data"].get("fill_info") and not t["log_data"]["fill_info"].get("was_fok")]

        fok_pnl = sum(t["trade"].pnl or 0 for t in fok_trades) if fok_trades else 0
        non_fok_pnl = sum(t["trade"].pnl or 0 for t in non_fok) if non_fok else 0

        return {
            "by_order_type": result,
            "fok_vs_limit": {
                "fok_count": len(fok_trades),
                "fok_avg_pnl": round(fok_pnl / len(fok_trades), 4) if fok_trades else 0,
                "non_fok_count": len(non_fok),
                "non_fok_avg_pnl": round(non_fok_pnl / len(non_fok), 4) if non_fok else 0,
            },
        }

    # ------------------------------------------------------------------
    # 15. Order Book Analysis
    # ------------------------------------------------------------------

    def _orderbook_analysis(self, trades: list[dict]) -> dict:
        winners = {"count": 0, "total_imbalance": 0.0, "total_spread": 0.0}
        losers = {"count": 0, "total_imbalance": 0.0, "total_spread": 0.0}
        imbalance_buckets = defaultdict(lambda: {"count": 0, "wins": 0, "total_pnl": 0.0})

        has_data = False
        for t in trades:
            ld = t["log_data"]
            obi_entry = ld.get("orderbook_imbalance_entry")
            if not obi_entry:
                continue

            has_data = True
            pnl = t["trade"].pnl or 0
            imbalance = obi_entry.get("imbalance", 0) or 0
            spread = obi_entry.get("spread", 0) or 0

            if pnl > 0:
                winners["count"] += 1
                winners["total_imbalance"] += imbalance
                winners["total_spread"] += spread
            else:
                losers["count"] += 1
                losers["total_imbalance"] += imbalance
                losers["total_spread"] += spread

            # Bucket by imbalance direction
            if imbalance > 0.2:
                key = "strong_bid"
            elif imbalance > 0:
                key = "slight_bid"
            elif imbalance > -0.2:
                key = "slight_ask"
            else:
                key = "strong_ask"

            imbalance_buckets[key]["count"] += 1
            imbalance_buckets[key]["total_pnl"] += pnl
            if pnl > 0:
                imbalance_buckets[key]["wins"] += 1

        if not has_data:
            return {}

        wc = winners["count"]
        lc = losers["count"]

        bucket_result = {}
        for key in ["strong_bid", "slight_bid", "slight_ask", "strong_ask"]:
            if key in imbalance_buckets:
                b = imbalance_buckets[key]
                c = b["count"]
                bucket_result[key] = {
                    "count": c,
                    "win_rate": round(b["wins"] / c, 4) if c else 0,
                    "avg_pnl": round(b["total_pnl"] / c, 4) if c else 0,
                }

        # Compute correlation between entry imbalance and PnL
        imbalances = []
        pnls = []
        for t in trades:
            ld = t["log_data"]
            obi = ld.get("orderbook_imbalance_entry")
            if obi:
                imbalances.append(obi.get("imbalance", 0) or 0)
                pnls.append(t["trade"].pnl or 0)

        imbalance_pnl_corr = self._pearson(imbalances, pnls)

        return {
            "winners": {
                "count": wc,
                "avg_imbalance_at_entry": round(winners["total_imbalance"] / wc, 4) if wc else 0,
                "avg_spread_at_entry": round(winners["total_spread"] / wc, 4) if wc else 0,
            },
            "losers": {
                "count": lc,
                "avg_imbalance_at_entry": round(losers["total_imbalance"] / lc, 4) if lc else 0,
                "avg_spread_at_entry": round(losers["total_spread"] / lc, 4) if lc else 0,
            },
            "by_imbalance_direction": bucket_result,
            "imbalance_vs_pnl_correlation": round(imbalance_pnl_corr, 4) if imbalance_pnl_corr is not None else None,
        }

    # ------------------------------------------------------------------
    # 16. Bayesian Analysis
    # ------------------------------------------------------------------

    def _bayesian_analysis(self, trades: list[dict]) -> dict:
        """Analyze Bayesian evidence effectiveness and gating behavior."""
        evidence_combinations = defaultdict(lambda: {"count": 0, "wins": 0, "total_pnl": 0.0})
        posterior_buckets = defaultdict(lambda: {"count": 0, "wins": 0, "total_pnl": 0.0})
        gate_passed = {"count": 0, "wins": 0, "total_pnl": 0.0}
        gate_blocked = {"count": 0, "potential_wins": 0, "potential_pnl": 0.0}
        fallback_mode = {"count": 0, "wins": 0, "total_pnl": 0.0}
        active_mode = {"count": 0, "wins": 0, "total_pnl": 0.0}
        posteriors = []
        pnls = []

        has_data = False
        for t in trades:
            ld = t["log_data"]
            bayesian = ld.get("bayesian")
            if not bayesian:
                continue

            has_data = True
            pnl = t["trade"].pnl or 0
            l1_evidence = bayesian.get("l1_evidence", "L1_NEUTRAL")
            l2_evidence = bayesian.get("l2_evidence", "L2_NEUTRAL")
            posterior = bayesian.get("posterior")
            confidence_gate = bayesian.get("confidence_gate", True)
            fallback = bayesian.get("fallback", False)

            # Track evidence combinations
            key = f"{l1_evidence}|{l2_evidence}"
            evidence_combinations[key]["count"] += 1
            evidence_combinations[key]["total_pnl"] += pnl
            if pnl > 0:
                evidence_combinations[key]["wins"] += 1

            # Track posterior distribution
            if posterior is not None:
                posterior_bucket = f"{int(posterior * 10) / 10:.1f}-{int(posterior * 10 + 1) / 10:.1f}"
                posterior_buckets[posterior_bucket]["count"] += 1
                posterior_buckets[posterior_bucket]["total_pnl"] += pnl
                if pnl > 0:
                    posterior_buckets[posterior_bucket]["wins"] += 1
                posteriors.append(posterior)
                pnls.append(pnl)

            # Track gate behavior
            if confidence_gate:
                gate_passed["count"] += 1
                gate_passed["total_pnl"] += pnl
                if pnl > 0:
                    gate_passed["wins"] += 1
            else:
                gate_blocked["count"] += 1
                gate_blocked["potential_pnl"] += pnl
                if pnl > 0:
                    gate_blocked["potential_wins"] += 1

            # Track fallback vs active mode
            if fallback:
                fallback_mode["count"] += 1
                fallback_mode["total_pnl"] += pnl
                if pnl > 0:
                    fallback_mode["wins"] += 1
            else:
                active_mode["count"] += 1
                active_mode["total_pnl"] += pnl
                if pnl > 0:
                    active_mode["wins"] += 1

        if not has_data:
            return {}

        # Compute evidence combination stats
        evidence_result = {}
        for key, data in sorted(evidence_combinations.items(), key=lambda x: -x[1]["count"]):
            c = data["count"]
            evidence_result[key] = {
                "count": c,
                "win_rate": round(data["wins"] / c, 4) if c else 0,
                "avg_pnl": round(data["total_pnl"] / c, 4) if c else 0,
            }

        # Compute posterior bucket stats
        posterior_result = {}
        for key in sorted(posterior_buckets.keys()):
            data = posterior_buckets[key]
            c = data["count"]
            posterior_result[key] = {
                "count": c,
                "win_rate": round(data["wins"] / c, 4) if c else 0,
                "avg_pnl": round(data["total_pnl"] / c, 4) if c else 0,
            }

        # Correlation between posterior and PnL
        posterior_pnl_corr = self._pearson(posteriors, pnls) if len(posteriors) >= 3 else None

        return {
            "evidence_combinations": evidence_result,
            "posterior_buckets": posterior_result,
            "posterior_vs_pnl_correlation": round(posterior_pnl_corr, 4) if posterior_pnl_corr is not None else None,
            "gate_passed": {
                "count": gate_passed["count"],
                "win_rate": round(gate_passed["wins"] / gate_passed["count"], 4) if gate_passed["count"] else 0,
                "avg_pnl": round(gate_passed["total_pnl"] / gate_passed["count"], 4) if gate_passed["count"] else 0,
            },
            "gate_blocked": {
                "count": gate_blocked["count"],
                "potential_win_rate": round(gate_blocked["potential_wins"] / gate_blocked["count"], 4) if gate_blocked["count"] else 0,
                "potential_avg_pnl": round(gate_blocked["potential_pnl"] / gate_blocked["count"], 4) if gate_blocked["count"] else 0,
            },
            "fallback_mode": {
                "count": fallback_mode["count"],
                "win_rate": round(fallback_mode["wins"] / fallback_mode["count"], 4) if fallback_mode["count"] else 0,
                "avg_pnl": round(fallback_mode["total_pnl"] / fallback_mode["count"], 4) if fallback_mode["count"] else 0,
            },
            "active_mode": {
                "count": active_mode["count"],
                "win_rate": round(active_mode["wins"] / active_mode["count"], 4) if active_mode["count"] else 0,
                "avg_pnl": round(active_mode["total_pnl"] / active_mode["count"], 4) if active_mode["count"] else 0,
            },
        }

    # ------------------------------------------------------------------
    # 17. 15-Minute Survival Analysis
    # ------------------------------------------------------------------

    def _survival_analysis(self, trades: list[dict]) -> dict:
        """
        Analyze why trades survive or fail within their 15-minute window.
        
        Key questions:
        1. Are we entering in high-volatility environments (ATR)?
        2. Are stops too tight relative to natural price movement (MAE vs stop)?
        3. Does exit liquidity correlate with slippage?
        4. When layers disagree, which L2 TF causes the most damage?
        """
        # ATR buckets
        atr_buckets = defaultdict(lambda: {"count": 0, "wins": 0, "total_pnl": 0.0})
        
        # Survival margin tracking
        survival_margins = []
        near_miss_winners = {"count": 0, "total_pnl": 0.0}
        
        # Stop efficiency by time zone
        stop_by_timezone = defaultdict(lambda: {"count": 0, "wins": 0, "total_pnl": 0.0, "margins": []})
        
        # Layer disagreement impact
        disagreement_impact = defaultdict(lambda: {"count": 0, "wins": 0, "total_pnl": 0.0})
        
        # Liquidity at exit (for trailing_stop exits)
        liquidity_at_stop = {"total_spread_bps": 0.0, "total_depth_ratio": 0.0, "count": 0}
        
        has_data = False
        for t in trades:
            ld = t["log_data"]
            pnl = t["trade"].pnl or 0
            won = pnl > 0
            
            # 1. Volatility (ATR) analysis
            volatility = ld.get("volatility", {})
            atr_bps = volatility.get("atr_normalized_bps")
            regime = volatility.get("volatility_regime", "unknown")
            if atr_bps is not None:
                has_data = True
                # Bucket by ATR regime
                atr_buckets[regime]["count"] += 1
                atr_buckets[regime]["total_pnl"] += pnl
                if won:
                    atr_buckets[regime]["wins"] += 1
            
            # 2. Survival buffer analysis
            survival = ld.get("survival_analysis", {})
            if survival:
                has_data = True
                margin = survival.get("survival_margin_bps")
                time_zone = survival.get("time_zone", "unknown")
                
                if margin is not None:
                    survival_margins.append(margin)
                    
                    # Track by time zone
                    stop_by_timezone[time_zone]["count"] += 1
                    stop_by_timezone[time_zone]["total_pnl"] += pnl
                    stop_by_timezone[time_zone]["margins"].append(margin)
                    if won:
                        stop_by_timezone[time_zone]["wins"] += 1
                
                # Near-miss winners
                if survival.get("near_miss_winner"):
                    near_miss_winners["count"] += 1
                    near_miss_winners["total_pnl"] += pnl
            
            # 3. Layer disagreement impact
            disagreement = ld.get("layer_disagreement", {})
            if disagreement and not disagreement.get("agreement", True):
                has_data = True
                dominant_tf = disagreement.get("dominant_conflict_tf", "unknown")
                vroc_conflict = disagreement.get("vroc_conflict", False)
                
                # Track dominant TF conflicts
                key = f"L2_{dominant_tf}_conflict" if dominant_tf else "L2_unknown_conflict"
                disagreement_impact[key]["count"] += 1
                disagreement_impact[key]["total_pnl"] += pnl
                if won:
                    disagreement_impact[key]["wins"] += 1
                
                # Track VROC conflicts separately
                if vroc_conflict:
                    disagreement_impact["VROC_unconfirmed"]["count"] += 1
                    disagreement_impact["VROC_unconfirmed"]["total_pnl"] += pnl
                    if won:
                        disagreement_impact["VROC_unconfirmed"]["wins"] += 1
            
            # 4. Liquidity at exit for trailing_stop
            exit_reason = ld.get("exit_reason", "")
            obi_exit = ld.get("orderbook_imbalance_exit", {})
            if exit_reason == "trailing_stop" and obi_exit:
                has_data = True
                spread_bps = obi_exit.get("spread_bps", 0)
                depth_ratio = obi_exit.get("depth_ratio", 0)
                liquidity_at_stop["total_spread_bps"] += spread_bps
                liquidity_at_stop["total_depth_ratio"] += depth_ratio
                liquidity_at_stop["count"] += 1
        
        if not has_data:
            return {}
        
        # Compute ATR regime stats
        atr_result = {}
        for regime in ["low", "medium", "high", "extreme", "unknown"]:
            data = atr_buckets[regime]
            if data["count"] > 0:
                atr_result[regime] = {
                    "count": data["count"],
                    "win_rate": round(data["wins"] / data["count"], 4),
                    "avg_pnl": round(data["total_pnl"] / data["count"], 4),
                }
        
        # Compute stop efficiency by time zone
        timezone_result = {}
        for tz, data in stop_by_timezone.items():
            if data["count"] > 0:
                margins = data["margins"]
                timezone_result[tz] = {
                    "count": data["count"],
                    "win_rate": round(data["wins"] / data["count"], 4),
                    "avg_pnl": round(data["total_pnl"] / data["count"], 4),
                    "avg_survival_margin_bps": round(sum(margins) / len(margins), 2) if margins else 0,
                }
        
        # Compute disagreement impact
        disagreement_result = {}
        for key, data in sorted(disagreement_impact.items(), key=lambda x: -x[1]["count"]):
            if data["count"] > 0:
                disagreement_result[key] = {
                    "count": data["count"],
                    "win_rate": round(data["wins"] / data["count"], 4),
                    "avg_pnl": round(data["total_pnl"] / data["count"], 4),
                }
        
        # Survival margin distribution
        margin_stats = {}
        if survival_margins:
            margin_stats = {
                "count": len(survival_margins),
                "avg_bps": round(sum(survival_margins) / len(survival_margins), 2),
                "min_bps": round(min(survival_margins), 2),
                "max_bps": round(max(survival_margins), 2),
                "median_bps": round(sorted(survival_margins)[len(survival_margins) // 2], 2),
            }
        
        # Liquidity stats
        liquidity_stats = {}
        if liquidity_at_stop["count"] > 0:
            liquidity_stats = {
                "count": liquidity_at_stop["count"],
                "avg_spread_bps": round(liquidity_at_stop["total_spread_bps"] / liquidity_at_stop["count"], 2),
                "avg_depth_ratio": round(liquidity_at_stop["total_depth_ratio"] / liquidity_at_stop["count"], 4),
            }
        
        return {
            "atr_at_entry": atr_result,
            "survival_margin_distribution": margin_stats,
            "near_miss_winners": {
                "count": near_miss_winners["count"],
                "total_pnl": round(near_miss_winners["total_pnl"], 4),
            },
            "stop_efficiency_by_timezone": timezone_result,
            "layer_disagreement_impact": disagreement_result,
            "liquidity_at_trailing_stop": liquidity_stats,
            "btc_token_divergence": self._btc_token_divergence_analysis(trades_with_log),
        }

    def _btc_token_divergence_analysis(self, trades_with_log: list[dict]) -> dict:
        """
        Analyze BTC vs Token divergence to evaluate survival buffer effectiveness.
        
        Tracks:
        - How often divergence blocked exits during survival buffer
        - Success rate of trades where divergence was detected
        - Average PnL of divergence-protected trades
        """
        divergence_blocked = {"count": 0, "wins": 0, "total_pnl": 0.0}
        normal_survival = {"count": 0, "wins": 0, "total_pnl": 0.0}
        liquidity_guarded = {"count": 0, "wins": 0, "total_pnl": 0.0}
        signal_decay_exits = {"count": 0, "wins": 0, "total_pnl": 0.0}
        
        for t in trades_with_log:
            trade = t["trade"]
            log_data = t.get("log_data", {})
            pnl = trade.pnl or 0
            won = pnl > 0
            
            sell_state = log_data.get("sell_state", {})
            signal = sell_state.get("signal", {})
            
            entry_btc_price = 0
            entry_spread_bps = 0
            buy_state = log_data.get("buy_state", {})
            if buy_state:
                entry_btc_price = buy_state.get("btc_price", 0)
            
            exit_reason = trade.notes.lower() if trade.notes else ""
            
            if "signal_decay_estop" in exit_reason:
                signal_decay_exits["count"] += 1
                signal_decay_exits["total_pnl"] += pnl
                if won:
                    signal_decay_exits["wins"] += 1
            elif "divergence" in exit_reason or "noise" in exit_reason:
                divergence_blocked["count"] += 1
                divergence_blocked["total_pnl"] += pnl
                if won:
                    divergence_blocked["wins"] += 1
            elif "liquidity_guard" in exit_reason or "stop-hunt" in exit_reason:
                liquidity_guarded["count"] += 1
                liquidity_guarded["total_pnl"] += pnl
                if won:
                    liquidity_guarded["wins"] += 1
            else:
                normal_survival["count"] += 1
                normal_survival["total_pnl"] += pnl
                if won:
                    normal_survival["wins"] += 1
        
        result = {}
        
        if divergence_blocked["count"] > 0:
            result["divergence_blocked"] = {
                "count": divergence_blocked["count"],
                "win_rate": round(divergence_blocked["wins"] / divergence_blocked["count"], 4),
                "avg_pnl": round(divergence_blocked["total_pnl"] / divergence_blocked["count"], 4),
            }
        
        if liquidity_guarded["count"] > 0:
            result["liquidity_guarded"] = {
                "count": liquidity_guarded["count"],
                "win_rate": round(liquidity_guarded["wins"] / liquidity_guarded["count"], 4),
                "avg_pnl": round(liquidity_guarded["total_pnl"] / liquidity_guarded["count"], 4),
            }
        
        if signal_decay_exits["count"] > 0:
            result["signal_decay_estop"] = {
                "count": signal_decay_exits["count"],
                "win_rate": round(signal_decay_exits["wins"] / signal_decay_exits["count"], 4),
                "avg_pnl": round(signal_decay_exits["total_pnl"] / signal_decay_exits["count"], 4),
            }
        
        total_with_features = divergence_blocked["count"] + liquidity_guarded["count"] + signal_decay_exits["count"]
        if total_with_features > 0:
            total_wins = divergence_blocked["wins"] + liquidity_guarded["wins"] + signal_decay_exits["wins"]
            total_pnl = divergence_blocked["total_pnl"] + liquidity_guarded["total_pnl"] + signal_decay_exits["total_pnl"]
            result["feature_protected_summary"] = {
                "total_count": total_with_features,
                "overall_win_rate": round(total_wins / total_with_features, 4),
                "overall_avg_pnl": round(total_pnl / total_with_features, 4),
            }
        
        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _pearson(x: list[float], y: list[float]) -> Optional[float]:
        """Compute Pearson correlation without numpy."""
        n = len(x)
        if n < 3:
            return None
        mean_x = sum(x) / n
        mean_y = sum(y) / n
        cov = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
        std_x = (sum((xi - mean_x) ** 2 for xi in x)) ** 0.5
        std_y = (sum((yi - mean_y) ** 2 for yi in y)) ** 0.5
        if std_x == 0 or std_y == 0:
            return 0.0
        return cov / (std_x * std_y)
