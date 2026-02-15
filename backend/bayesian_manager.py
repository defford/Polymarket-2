"""
BayesianManager — Per-bot Bayesian inference for signal weighting.

Computes P(Win|Signals) using Bayes' theorem:
  P(Win|Signals) = (P(Signals|Win) * P(Win)) / P(Signals)

Evidence categories are binned from Layer 1 and Layer 2 signals.
Likelihoods are tracked per (L1_evidence, L2_evidence) pair.
"""

import logging
from typing import Optional, Tuple
from datetime import datetime, timezone

import database as db
from config import BayesianConfig

logger = logging.getLogger(__name__)

L1_THRESHOLDS = [
    (0.5, "L1_BULLISH_STRONG"),
    (0.2, "L1_BULLISH_WEAK"),
    (-0.2, "L1_NEUTRAL"),
    (-0.5, "L1_BEARISH_WEAK"),
    (-float('inf'), "L1_BEARISH_STRONG"),
]

L2_THRESHOLDS = [
    (0.5, "L2_BULLISH_STRONG"),
    (0.2, "L2_BULLISH_WEAK"),
    (-0.2, "L2_NEUTRAL"),
    (-0.5, "L2_BEARISH_WEAK"),
    (-float('inf'), "L2_BEARISH_STRONG"),
]


def bin_direction(direction: float, thresholds: list) -> str:
    """Bin a direction score into an evidence category."""
    for threshold, category in thresholds:
        if direction >= threshold:
            return category
    return thresholds[-1][1]


def bin_l1_evidence(direction: float) -> str:
    """Bin Layer 1 direction into evidence category."""
    return bin_direction(direction, L1_THRESHOLDS)


def bin_l2_evidence(direction: float) -> str:
    """Bin Layer 2 direction into evidence category."""
    return bin_direction(direction, L2_THRESHOLDS)


class BayesianManager:
    """
    Manages Bayesian inference for a single bot.
    
    Key methods:
    - get_prior(): Rolling P(Win) from last N trades
    - get_likelihood(): P(Evidence|Outcome) from likelihood table
    - compute_posterior(): P(Win|Evidence) using Bayes' theorem
    - record_outcome(): Update likelihood table after trade
    """
    
    CONFIDENCE_THRESHOLD = 0.4
    
    def __init__(self, bot_id: int, config: BayesianConfig = None):
        self.bot_id = bot_id
        self.config = config or BayesianConfig()
        self._cached_prior: Optional[float] = None
        self._cache_timestamp: Optional[datetime] = None
    
    def bin_evidence(self, l1_direction: float, l2_direction: float) -> Tuple[str, str]:
        """Convert raw direction scores to evidence categories."""
        l1_evidence = bin_l1_evidence(l1_direction)
        l2_evidence = bin_l2_evidence(l2_direction)
        return l1_evidence, l2_evidence
    
    def get_prior(self) -> float:
        """
        Compute rolling prior P(Win) from last N trades.
        Cached for performance (refreshed every 60s).
        """
        now = datetime.now(timezone.utc)
        if self._cached_prior and self._cache_timestamp:
            if (now - self._cache_timestamp).total_seconds() < 60:
                return self._cached_prior
        
        total_trades = db.get_bot_trade_count(self.bot_id, limit=self.config.rolling_window)
        if total_trades < self.config.min_sample_size:
            return 0.5
        
        wins = db.get_bot_win_count(self.bot_id, limit=self.config.rolling_window)
        prior = (wins + self.config.smoothing_alpha) / (total_trades + 2 * self.config.smoothing_alpha)
        
        self._cached_prior = prior
        self._cache_timestamp = now
        return prior
    
    def get_likelihood(self, l1_evidence: str, l2_evidence: str, outcome: str) -> Optional[float]:
        """
        Get P(Evidence|Outcome) from likelihood table.
        
        outcome: "win" or "loss"
        Uses Laplace smoothing to avoid zero probabilities.
        """
        row = db.get_bayesian_likelihood(self.bot_id, l1_evidence, l2_evidence)
        
        if row is None:
            return None
        
        alpha = self.config.smoothing_alpha
        if outcome == "win":
            return (row['wins'] + alpha) / (row['total'] + 2 * alpha)
        else:
            return (row['losses'] + alpha) / (row['total'] + 2 * alpha)
    
    def has_sufficient_data(self) -> bool:
        """Check if we have enough history to use Bayesian inference."""
        total = db.get_bot_trade_count(self.bot_id, limit=self.config.rolling_window)
        return total >= self.config.min_sample_size
    
    def compute_posterior(self, l1_evidence: str, l2_evidence: str) -> dict:
        """
        Compute P(Win|Evidence) using Bayes' theorem.
        
        Returns:
            dict with:
                - posterior: float (P(Win|Evidence))
                - prior: float (P(Win))
                - confidence_gate: bool (True if posterior >= threshold)
                - fallback: bool (True if using fixed weights)
                - reason: str
        """
        if not self.has_sufficient_data():
            return {
                "posterior": self.config.default_confidence,
                "prior": 0.5,
                "confidence_gate": True,
                "fallback": True,
                "reason": "insufficient_history",
            }
        
        prior = self.get_prior()
        
        p_evidence_given_win = self.get_likelihood(l1_evidence, l2_evidence, "win")
        p_evidence_given_loss = self.get_likelihood(l1_evidence, l2_evidence, "loss")
        
        if p_evidence_given_win is None or p_evidence_given_loss is None:
            return {
                "posterior": self.config.default_confidence,
                "prior": prior,
                "confidence_gate": True,
                "fallback": True,
                "reason": "unseen_evidence_combination",
            }
        
        p_loss = 1 - prior
        p_evidence = p_evidence_given_win * prior + p_evidence_given_loss * p_loss
        
        if p_evidence == 0:
            posterior = 0.5
        else:
            posterior = (p_evidence_given_win * prior) / p_evidence
        
        confidence_gate = posterior >= self.CONFIDENCE_THRESHOLD
        
        return {
            "posterior": posterior,
            "prior": prior,
            "confidence_gate": confidence_gate,
            "fallback": False,
            "reason": "ok" if confidence_gate else f"posterior_{posterior:.2f}_below_threshold",
        }
    
    def record_outcome(self, l1_evidence: str, l2_evidence: str, won: bool):
        """
        Update likelihood table after trade resolves.
        
        Args:
            l1_evidence: Layer 1 evidence category
            l2_evidence: Layer 2 evidence category
            won: True if trade was profitable
        """
        db.update_bayesian_likelihood(
            bot_id=self.bot_id,
            l1_evidence=l1_evidence,
            l2_evidence=l2_evidence,
            won=won,
        )
        self._cached_prior = None
        logger.info(
            f"Bayesian likelihood updated: bot={self.bot_id} "
            f"l1={l1_evidence} l2={l2_evidence} won={won}"
        )
    
    def get_likelihood_table(self) -> list[dict]:
        """Get all likelihood rows for this bot (for API/debugging)."""
        return db.get_all_bayesian_likelihoods(self.bot_id)
    
    def get_stats(self) -> dict:
        """Get Bayesian statistics for this bot."""
        total_trades = db.get_bot_trade_count(self.bot_id, limit=self.config.rolling_window)
        wins = db.get_bot_win_count(self.bot_id, limit=self.config.rolling_window)
        likelihood_rows = self.get_likelihood_table()
        
        return {
            "bot_id": self.bot_id,
            "total_trades": total_trades,
            "wins": wins,
            "prior": self.get_prior() if total_trades >= self.config.min_sample_size else None,
            "sufficient_data": self.has_sufficient_data(),
            "min_sample_size": self.config.min_sample_size,
            "evidence_combinations": len(likelihood_rows),
            "config": {
                "enabled": self.config.enabled,
                "rolling_window": self.config.rolling_window,
                "confidence_threshold": self.CONFIDENCE_THRESHOLD,
            },
        }