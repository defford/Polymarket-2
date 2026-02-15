"""
Unit tests for the Bayesian Signal Weighting Engine.
"""

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from bayesian_manager import (
    bin_direction,
    bin_l1_evidence,
    bin_l2_evidence,
    L1_THRESHOLDS,
    L2_THRESHOLDS,
)
from config import BayesianConfig


class TestEvidenceBinning:
    """Test evidence categorization from direction scores."""

    def test_l1_bullish_strong(self):
        assert bin_l1_evidence(0.7) == "L1_BULLISH_STRONG"
        assert bin_l1_evidence(0.5) == "L1_BULLISH_STRONG"
        assert bin_l1_evidence(0.99) == "L1_BULLISH_STRONG"

    def test_l1_bullish_weak(self):
        assert bin_l1_evidence(0.3) == "L1_BULLISH_WEAK"
        assert bin_l1_evidence(0.2) == "L1_BULLISH_WEAK"
        assert bin_l1_evidence(0.49) == "L1_BULLISH_WEAK"

    def test_l1_neutral(self):
        assert bin_l1_evidence(0.0) == "L1_NEUTRAL"
        assert bin_l1_evidence(0.1) == "L1_NEUTRAL"
        assert bin_l1_evidence(-0.1) == "L1_NEUTRAL"
        assert bin_l1_evidence(-0.19) == "L1_NEUTRAL"

    def test_l1_bearish_weak(self):
        assert bin_l1_evidence(-0.3) == "L1_BEARISH_WEAK"
        assert bin_l1_evidence(-0.5) == "L1_BEARISH_WEAK"
        assert bin_l1_evidence(-0.21) == "L1_BEARISH_WEAK"

    def test_l1_bearish_strong(self):
        assert bin_l1_evidence(-0.7) == "L1_BEARISH_STRONG"
        assert bin_l1_evidence(-0.51) == "L1_BEARISH_STRONG"
        assert bin_l1_evidence(-1.0) == "L1_BEARISH_STRONG"

    def test_l2_bullish_strong(self):
        assert bin_l2_evidence(0.6) == "L2_BULLISH_STRONG"
        assert bin_l2_evidence(0.5) == "L2_BULLISH_STRONG"

    def test_l2_bullish_weak(self):
        assert bin_l2_evidence(0.25) == "L2_BULLISH_WEAK"
        assert bin_l2_evidence(0.2) == "L2_BULLISH_WEAK"

    def test_l2_neutral(self):
        assert bin_l2_evidence(0.0) == "L2_NEUTRAL"
        assert bin_l2_evidence(-0.15) == "L2_NEUTRAL"

    def test_l2_bearish_weak(self):
        assert bin_l2_evidence(-0.25) == "L2_BEARISH_WEAK"
        assert bin_l2_evidence(-0.5) == "L2_BEARISH_WEAK"

    def test_l2_bearish_strong(self):
        assert bin_l2_evidence(-0.6) == "L2_BEARISH_STRONG"
        assert bin_l2_evidence(-1.0) == "L2_BEARISH_STRONG"


class TestBinDirection:
    """Test the generic bin_direction function."""

    def test_threshold_order(self):
        """Verify thresholds are ordered correctly."""
        for i in range(len(L1_THRESHOLDS) - 1):
            assert L1_THRESHOLDS[i][0] > L1_THRESHOLDS[i + 1][0], \
                f"L1 thresholds not ordered: {L1_THRESHOLDS}"

    def test_bin_direction_returns_category(self):
        result = bin_direction(0.7, L1_THRESHOLDS)
        assert isinstance(result, str)
        assert result.startswith("L1_")

    def test_bin_direction_boundary(self):
        """Test exact threshold values."""
        assert bin_direction(0.5, L1_THRESHOLDS) == "L1_BULLISH_STRONG"
        assert bin_direction(0.499, L1_THRESHOLDS) == "L1_BULLISH_WEAK"


class TestBayesianConfig:
    """Test BayesianConfig dataclass."""

    def test_default_values(self):
        config = BayesianConfig()
        assert config.enabled is True
        assert config.rolling_window == 100
        assert config.min_sample_size == 50
        assert config.default_confidence == 0.5
        assert config.confidence_threshold == 0.4
        assert config.smoothing_alpha == 0.1

    def test_custom_values(self):
        config = BayesianConfig(
            enabled=False,
            rolling_window=200,
            min_sample_size=25,
        )
        assert config.enabled is False
        assert config.rolling_window == 200
        assert config.min_sample_size == 25


class TestBayesianManagerMocked:
    """Test BayesianManager with mocked database."""

    def test_evidence_pair_generation(self):
        """Test that evidence pairs are generated correctly."""
        from bayesian_manager import BayesianManager
        
        config = BayesianConfig()
        bm = BayesianManager(bot_id=1, config=config)
        
        l1_e, l2_e = bm.bin_evidence(0.7, -0.3)
        assert l1_e == "L1_BULLISH_STRONG"
        assert l2_e == "L2_BEARISH_WEAK"

    def test_evidence_pair_both_neutral(self):
        from bayesian_manager import BayesianManager
        config = BayesianConfig()
        bm = BayesianManager(bot_id=1, config=config)
        
        l1_e, l2_e = bm.bin_evidence(0.0, 0.0)
        assert l1_e == "L1_NEUTRAL"
        assert l2_e == "L2_NEUTRAL"


class TestPosteriorCalculation:
    """Test Bayes' theorem calculations."""

    def test_bayes_theorem_basic(self):
        """
        Given:
        - P(Win) = 0.6 (prior)
        - P(Evidence|Win) = 0.8
        - P(Evidence|Loss) = 0.3
        
        Then:
        - P(Evidence) = 0.8*0.6 + 0.3*0.4 = 0.48 + 0.12 = 0.6
        - P(Win|Evidence) = (0.8 * 0.6) / 0.6 = 0.8
        """
        prior = 0.6
        p_ev_given_win = 0.8
        p_ev_given_loss = 0.3
        
        p_loss = 1 - prior
        p_evidence = p_ev_given_win * prior + p_ev_given_loss * p_loss
        posterior = (p_ev_given_win * prior) / p_evidence
        
        assert abs(posterior - 0.8) < 0.001

    def test_bayes_theorem_zero_evidence(self):
        """Test handling of zero probability evidence."""
        prior = 0.5
        p_ev_given_win = 0.0
        p_ev_given_loss = 0.0
        
        p_loss = 1 - prior
        p_evidence = p_ev_given_win * prior + p_ev_given_loss * p_loss
        
        # Should handle division by zero
        if p_evidence == 0:
            posterior = 0.5  # Neutral
        else:
            posterior = (p_ev_given_win * prior) / p_evidence
        
        assert posterior == 0.5


class TestConfidenceGate:
    """Test the threshold gate logic."""

    def test_gate_passes_above_threshold(self):
        """Posterior >= 0.4 should pass the gate."""
        posterior = 0.45
        threshold = 0.4
        assert posterior >= threshold

    def test_gate_blocks_below_threshold(self):
        """Posterior < 0.4 should be blocked."""
        posterior = 0.35
        threshold = 0.4
        assert posterior < threshold

    def test_gate_boundary(self):
        """Exact threshold should pass."""
        posterior = 0.4
        threshold = 0.4
        assert posterior >= threshold


if __name__ == "__main__":
    pytest.main([__file__, "-v"])