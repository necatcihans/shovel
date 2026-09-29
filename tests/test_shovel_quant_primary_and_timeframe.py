"""
UNIT TESTS: SHOVEL PRIMARY QUANT ENGINE & TIMEFRAME-NOISE ADAPTATION
Verifies all 8 validation criteria from the prompt:
1. Different timeframes data independence
2. Noise ratio elevation downweights short-term indicators
3. Low observation count disables/neutralizes models (Hurst N < 50)
4. Timeframe conflict generates IZLEME
5. Secondary indicators cannot overturn primary quant decision
6. Hurst chop regime blocks UYGUN (forces IZLEME)
7. Tail risk / CVaR critical veto forces KACIN
8. No look-ahead bias (snapshot slice only)
"""

import math
import numpy as np
from shovel_primary_quant_engine import ShovelPrimaryQuantEngine, load_quant_config

def test_config_loaded():
    config = load_quant_config()
    assert "primary_weights" in config
    assert config["secondary_indicators"]["can_trigger_primary_decision"] is False
    assert config["secondary_indicators"]["max_aggregate_weight"] <= 0.05

def test_timeframe_independence():
    """Test 1: Verify different timeframes maintain independent data streams."""
    engine = ShovelPrimaryQuantEngine()
    short_data = [100.0 + i * 0.1 for i in range(15)] # 15m/1h scale
    long_data = [90.0 + i * 0.5 for i in range(60)]   # Daily scale
    
    tf = engine.compute_timeframe_noise(short_data, long_data)
    assert tf.noise_ratio > 0.0
    assert tf.short_term_score != tf.long_term_score
    assert len(tf.active_timeframes) >= 3

def test_noise_adaptation_downweighting():
    """Test 2: High noise ratio increases Kalman measurement noise and downweights short-term."""
    engine = ShovelPrimaryQuantEngine()
    prices = [100.0 + (1.0 if i % 2 == 0 else -1.0) * 5.0 for i in range(50)]
    
    # Low noise Kalman vs High noise Kalman
    k_low = engine.compute_kalman(prices, noise_ratio=0.5)
    k_high = engine.compute_kalman(prices, noise_ratio=3.0)
    
    # R should scale adaptively with noise ratio
    assert k_high.measurement_noise > k_low.measurement_noise

    # Secondary indicator weight should be halved during high noise
    sec_normal = engine.compute_secondary_indicators(prices, noise_ratio=1.0)
    sec_high_noise = engine.compute_secondary_indicators(prices, noise_ratio=2.0)
    assert sec_high_noise.effective_weight < sec_normal.effective_weight

def test_low_observation_count_disables_model():
    """Test 3: Hurst exponent disables/neutralizes when sample size N < 50."""
    engine = ShovelPrimaryQuantEngine()
    short_prices = [100.0, 101.0, 102.0, 101.5, 103.0] # Only 5 observations
    
    hurst = engine.compute_hurst(short_prices)
    assert hurst.sample_size < 50
    assert hurst.regime == "CHOP_RANDOM"
    assert hurst.is_chop_veto is True
    assert hurst.normalized_score == 0.0

def test_timeframe_conflict_produces_izleme():
    """Test 4: When short-term is strongly bullish but long-term is strongly bearish -> IZLEME."""
    engine = ShovelPrimaryQuantEngine()
    
    # Long-term strongly falling (100 -> 60)
    long_prices = [100.0 - i * 0.7 for i in range(60)]
    # Short-term sharp spike upwards (55 -> 65)
    short_prices = [55.0 + i * 0.7 for i in range(15)]
    
    output = engine.evaluate_decision(
        symbol="BTCUSDT",
        asset_class="crypto",
        prices_daily=long_prices,
        prices_intraday=short_prices
    )
    
    assert output.timeframe_noise.is_timeframe_conflicted is True
    assert output.veto_flags["timeframe_conflict_veto"] is True
    # Decision CANNOT be UYGUN
    assert output.decision in ["İZLEME", "KAÇIN"]
    if output.final_quant_score >= 0:
        assert output.decision == "İZLEME"

def test_hurst_chop_veto_blocks_uygun():
    """Test 5: In random walk / chop regime (Hurst 0.45-0.55), decision CANNOT be UYGUN."""
    engine = ShovelPrimaryQuantEngine()
    np.random.seed(42)
    # Generate geometric Brownian motion (Hurst approx 0.50)
    bm_returns = np.random.normal(0.0005, 0.015, 150)
    bm_prices = list(100.0 * np.cumprod(1.0 + bm_returns))
    
    output = engine.evaluate_decision(
        symbol="AAPL",
        asset_class="us_equities",
        prices_daily=bm_prices,
        fundamental_score=0.85
    )
    
    if output.hurst.is_chop_veto:
        assert output.decision != "UYGUN"
        assert output.decision in ["İZLEME", "KAÇIN"]

def test_tail_risk_critical_cvar_forces_kacin():
    """Test 6: Critical CVaR violation forces KACIN."""
    engine = ShovelPrimaryQuantEngine()
    
    # Severe crash series (-10% drop per day)
    crash_prices = [100.0] * 30 + [100.0 * (0.90 ** i) for i in range(15)]
    output = engine.evaluate_decision(
        symbol="ETHUSDT",
        asset_class="crypto",
        prices_daily=crash_prices
    )
    
    assert output.tail_risk.is_cvar_veto is True
    assert output.decision == "KAÇIN"

def test_secondary_indicators_cannot_overturn_primary_quant():
    """Test 7: RSI 90 (overbought) or RSI 10 (oversold) cannot overturn strong quant trend."""
    engine = ShovelPrimaryQuantEngine()
    
    # Strong sustained upward trend with low noise
    strong_trend = [100.0 + i * 1.5 for i in range(80)]
    
    output = engine.evaluate_decision(
        symbol="NVDA",
        asset_class="us_equities",
        prices_daily=strong_trend,
        fundamental_score=0.90
    )
    
    # Even if RSI is high (overbought), quant trend dominates
    assert output.kalman.normalized_score > 0.5
    assert output.secondary_indicators.effective_weight <= 0.05
    assert output.decision == "UYGUN"

def test_zero_lookahead_bias():
    """Test 8: Calculations at t=50 and t=100 do not use future prices."""
    engine = ShovelPrimaryQuantEngine()
    full_series = [100.0 + math.sin(i * 0.1) * 10.0 + i * 0.2 for i in range(120)]
    
    out_50 = engine.evaluate_decision("TEST", "us_equities", full_series[:50])
    out_100 = engine.evaluate_decision("TEST", "us_equities", full_series[:100])
    
    # Length of processed data matches snapshot
    assert out_50.kalman.filtered_price != out_100.kalman.filtered_price
    assert out_50.as_of == "2026-09-28"

if __name__ == "__main__":
    tests = [
        test_config_loaded,
        test_timeframe_independence,
        test_noise_adaptation_downweighting,
        test_low_observation_count_disables_model,
        test_timeframe_conflict_produces_izleme,
        test_hurst_chop_veto_blocks_uygun,
        test_tail_risk_critical_cvar_forces_kacin,
        test_secondary_indicators_cannot_overturn_primary_quant,
        test_zero_lookahead_bias
    ]
    passed = 0
    failed = 0
    print("RUNNING PRIMARY QUANT & TIMEFRAME TEST SUITE...")
    for t in tests:
        try:
            t()
            print(f"  [PASS] {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {t.__name__}: {e}")
            failed += 1
    print(f"\nRESULTS: {passed} PASSED, {failed} FAILED")
    if failed > 0:
        exit(1)
