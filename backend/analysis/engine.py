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
