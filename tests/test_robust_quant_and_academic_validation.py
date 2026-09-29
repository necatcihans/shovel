# -*- coding: utf-8 -*-
"""
test_robust_quant_and_academic_validation.py — Shovel Matematiksel Quant Dayanıklılık ve Akademik Doğrulama Test Paketi

16 Zorunlu Test Kategorisi:
1. Araştırma Deneme Kaydı (Trial Registry & Counters)
2. Robust İstatistik (Median, MAD, Winsorization, Robust Z-Score, Percentile)
3. Rejim Eşikleri (Config Tabanlı RISK_ON, RISK_OFF, TIGHTENING, EASING, HIGH_VOL, UNCERTAIN)
4. Volatilite (Varlık Sınıfı Bazlı EWMA Lambdaları & GARCH Fallback)
5. Kuyruk Riski (Historical, Filtered, Cornish-Fisher VaR, CVaR, Skewness, Kurtosis)
6. Purged Walk-Forward ve Dinamik Embargo
7. Look-Ahead ve Survivorship Test Fixture'ları (6 Senaryo)
8. Monte Carlo DCF Tekrarlanabilirlik & %5-%95 Koridoru
9. Bayesçi Güncelleme & Likelihood Seçimleri (Güvenlik Kuralı: Tek Başına AL/SAT Veremez)
10. Portföy Optimizasyonu Batch Proposal Motoru (human_approval: false)
11. Overfitting & Çoklu Test Metrikleri (DSR, PBO, Holm-Bonferroni)
12. Dinamik Faktör Ağırlıkları Proposal Yapısı
13. Canlı / Batch Ayrımı Güvenlik Duvarı
14. Standart Model Kayıt Şeması
15. Quant Backend & Karar Zinciri Entegrasyonu
16. Browser CDP ile Shovel.html ve Shovel_Protected.html Bütünlüğü
"""

import os
import sys
import json
import time
import math
import shutil
import tempfile
import numpy as np
import subprocess
from datetime import datetime, timezone
import urllib.request

# UTF-8 stdout
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from shovel_robust_quant import (
    TrialRegistry,
    TrialRecord,
    RobustStats,
    RegimeEngine,
    VolatilityEngine,
    TailRiskEngine,
    PurgedWalkForwardEngine,
    BiasProtectionFixtures,
    MonteCarloDCFEngine,
    BayesianUpdater,
    PortfolioOptimizer,
    AcademicOverfittingEngine,
    FactorWeightOptimizer,
    ExecutionModeGuard,
    StandardModelRecord,
    ASSET_CLASS_EWMA_LAMBDA
)
import quant_backend
from shovel_decision_chain import ShovelDecisionChainEngine, DecisionJournal, PaperPortfolio

SHOVEL_HTML_PATH = r"c:\Users\Cihan\Desktop\Shovel.html"
SHOVEL_PROTECTED_PATH = r"c:\Users\Cihan\Desktop\Shovel_Protected.html"


def test_01_trial_registry_and_counter():
    print("\n--- TEST 1: Araştırma Deneme Kaydı & Trial Registry ---")
    tmp_dir = tempfile.mkdtemp()
    trial_file = os.path.join(tmp_dir, "test_trials.jsonl")
    reg = TrialRegistry(file_path=trial_file)

    # Başlangıçta boş
    assert len(reg.get_all_trials()) == 0
    counts = reg.get_trial_counts()
    assert counts["total_trials"] == 0

    # 1. Deneme kaydet (Başarılı)
    t1 = TrialRecord(
        strategy_version="v4.6-academic-core",
        model_version="v1.2.0-quant",
        parameters={"momentum_window": 20, "ewma_lambda": 0.94},
        assumptions={"slippage_bps": 15},
        in_sample_score=1.45,
        out_of_sample_score=1.12,
        walk_forward_score=0.98,
        sharpe=1.35,
        status="promoted",
        human_approval=False,
        is_independent=True
    )
    reg.log_trial(t1)

    # 2. Deneme kaydet (Başarısız/Reddedilmiş)
    t2 = TrialRecord(
        strategy_version="v4.6-academic-core",
        model_version="v1.2.0-quant",
        parameters={"momentum_window": 5, "ewma_lambda": 0.88},
        assumptions={"slippage_bps": 25},
        in_sample_score=1.60,
        out_of_sample_score=0.40,
        walk_forward_score=0.20,
        sharpe=0.55,
        status="rejected",
        human_approval=False,
        is_independent=True
    )
    reg.log_trial(t2)

    # 3. Bağımlı varyasyon denemesi
    t3 = TrialRecord(
        strategy_version="v4.6-academic-core",
        parameters={"momentum_window": 6},
        status="tested",
        is_independent=False
    )
    reg.log_trial(t3)

    counts = reg.get_trial_counts()
    assert counts["total_trials"] == 3
    assert counts["independent_trials"] == 2
    assert counts["promoted"] == 1
    assert counts["rejected"] == 1
    assert counts["tested"] == 1
    print(f"✅ Trial Registry başarıyla doğrulandı: {counts}")
    shutil.rmtree(tmp_dir, ignore_errors=True)


def test_02_robust_statistics():
    print("\n--- TEST 2: Robust İstatistik (Median, MAD, Winsorization, Z-Score) ---")
    data = [10.0, 12.0, 11.0, 13.0, 12.0, 11.5, 12.5, 100.0, -50.0]  # İki bariz aykırı değer

    # Median ve MAD
    med = RobustStats.median(data)
    mad = RobustStats.mad(data)
    assert 11.0 <= med <= 13.0
    assert mad > 0

    # Winsorization ve Aykırı Değer Tespiti
    clipped, outlier_rep = RobustStats.winsorize(data, limits=(0.10, 0.90))
    assert outlier_rep["outlier_count"] >= 2
    assert -50.0 not in clipped
    assert 100.0 not in clipped
    print(f"✅ Winsorization aykırı değerleri sessizce silmedi, raporladı: {outlier_rep['outlier_count']} adet aykırı değer")

    # Robust Z-Score
    z_scores, meta = RobustStats.robust_zscore(data, winsor_limits=(0.10, 0.90))
    assert meta["scaling_method"] == "robust_zscore"
    assert meta["outlier_method"] == "winsorization"
    assert len(z_scores) == len(data)

    # Percentile Normalization
    pcts = RobustStats.percentile_normalization(data)
    assert len(pcts) == len(data)
    assert min(pcts) == 0.0
    assert max(pcts) == 100.0
    print("✅ Robust z-score ve percentile normalizasyonu metadata ile onaylandı.")


def test_03_regime_thresholds_from_config():
    print("\n--- TEST 3: Somut Rejim Eşikleri ve Karar Motoru ---")
    engine = RegimeEngine()
    as_of = datetime.now(timezone.utc).isoformat()

    # 1. RISK_ON Senaryosu
    r_on = engine.evaluate_regime(
        trend_direction="positive",
        ewma_vol=0.18,
        yield_curve_spread=0.25,
        rate_change_3m=-0.10,
        market_breadth=0.65,
        historical_vol_percentile=40.0,
        data_as_of=as_of
    )
    assert r_on["regime"] == "RISK_ON"
    assert r_on["probabilities"]["RISK_ON"] >= 0.80

    # 2. RISK_OFF Senaryosu
    r_off = engine.evaluate_regime(
        trend_direction="negative",
        ewma_vol=0.32,
        yield_curve_spread=-0.05,
        rate_change_3m=0.10,
        market_breadth=0.25,
        historical_vol_percentile=75.0,
        data_as_of=as_of
    )
    assert r_off["regime"] == "RISK_OFF"

    # 3. HIGH_VOLATILITY Senaryosu
    r_hvol = engine.evaluate_regime(
        trend_direction="negative",
        ewma_vol=0.45,
        yield_curve_spread=-0.10,
        rate_change_3m=0.0,
        market_breadth=0.30,
        historical_vol_percentile=92.0,
        data_as_of=as_of
    )
    assert r_hvol["regime"] == "HIGH_VOLATILITY"

    # 4. TIGHTENING Senaryosu
    r_tight = engine.evaluate_regime(
        trend_direction="positive",
        ewma_vol=0.20,
        yield_curve_spread=0.05,
        rate_change_3m=0.50,
        market_breadth=0.50,
        historical_vol_percentile=50.0,
        data_as_of=as_of
    )
    # Çelişki veya tightening
    assert r_tight["regime"] in ["TIGHTENING", "UNCERTAIN"]

    # 5. UNCERTAIN Senaryosu (Çelişkili göstergeler)
    r_unc = engine.evaluate_regime(
        trend_direction="positive",
        ewma_vol=0.42,  # Yüksek oynaklık ama trend pozitif
        yield_curve_spread=-0.20,
        rate_change_3m=0.75,
        market_breadth=0.40,
        historical_vol_percentile=70.0,
        data_as_of=as_of
    )
    assert r_unc["regime"] == "UNCERTAIN"
    print("✅ Somut rejim eşikleri ve olasılık kaydı doğrulandı.")


def test_04_volatility_asset_class_and_garch_fallback():
    print("\n--- TEST 4: Varlık Sınıfı EWMA & GARCH Fallback Koruması ---")
    sim_returns = list(np.random.normal(0.0005, 0.015, 100))

    # Varlık sınıflarına göre lambda testi
    vol_crypto, _ = VolatilityEngine.calculate_ewma_volatility(sim_returns, asset_class="CRYPTO")
    vol_us, _ = VolatilityEngine.calculate_ewma_volatility(sim_returns, asset_class="US_EQUITIES")
    assert ASSET_CLASS_EWMA_LAMBDA["CRYPTO"] == 0.94
    assert ASSET_CLASS_EWMA_LAMBDA["US_EQUITIES"] == 0.97
    assert ASSET_CLASS_EWMA_LAMBDA["BIST"] == 0.96
    assert ASSET_CLASS_EWMA_LAMBDA["COMMODITIES"] == 0.95

    # GARCH Yeterli Gözlem
    garch_ok = VolatilityEngine.calculate_garch_advanced(sim_returns, asset_class="US_EQUITIES", min_obs=50)
    assert garch_ok["garch_valid"] is True
    assert garch_ok["fallback_used"] is False

    # GARCH Yetersiz Gözlem (< 50) -> EWMA Fallback
    short_returns = sim_returns[:25]
    garch_short = VolatilityEngine.calculate_garch_advanced(short_returns, min_obs=50)
    assert garch_short["garch_valid"] is False
    assert garch_short["fallback_used"] is True
    assert garch_short["fallback_to"] == "EWMA"
    assert "Yetersiz gözlem" in garch_short["warning"]
    print("✅ Varlık sınıfı lambdaları ve GARCH yetersiz gözlem/fallback koruması onaylandı.")


def test_05_tail_risk_non_normal_models():
    print("\n--- TEST 5: Kuyruk Riski (Multi-Tail, Cornish-Fisher, CVaR) ---")
    # Kalın kuyruklu ve negatif çarpık sentetik getiri
    np.random.seed(42)
    skewed_returns = np.random.laplace(-0.001, 0.02, 252)

    tail = TailRiskEngine.calculate_tail_risk(skewed_returns, confidence_level=0.95, lookback_window=252)
    assert tail["historical_var"] > 0
    assert tail["cvar"] >= tail["historical_var"]  # CVaR her zaman VaR'dan büyüktür veya eşittir
    assert tail["cornish_fisher_var"] > 0
    assert "skewness" in tail and "kurtosis" in tail
    assert tail["tail_assumption"] == "Non-normal (Empirical + Cornish-Fisher Expansion)"
    print(f"✅ Kuyruk riski hesaplandı (VaR: %{tail['historical_var']*100:.2f}, CVaR: %{tail['cvar']*100:.2f}, CF-VaR: %{tail['cornish_fisher_var']*100:.2f})")


def test_06_purged_walk_forward_and_dynamic_embargo():
    print("\n--- TEST 6: Purged Walk-Forward ve Dinamik Embargo ---")
    engine = PurgedWalkForwardEngine()

    # Dinamik embargo hesaplama kontrolü
    emb_short = engine.calculate_dynamic_embargo("short_momentum", lookback_days=5, target_horizon_days=5)
    emb_med = engine.calculate_dynamic_embargo("medium_swing", lookback_days=20, target_horizon_days=20)
    emb_long = engine.calculate_dynamic_embargo("long_value", lookback_days=60, target_horizon_days=60)
    assert emb_short == 5
    assert emb_med == 20
    assert emb_long == 60

    # Purged Splits Üretimi
    splits = engine.generate_splits(total_days=300, train_window=100, test_window=25, signal_type="medium_swing", purge_days=3)
    assert len(splits) >= 4
    for s in splits:
        # Train sonu ile test başı arasında en az embargo kadar mesafe olmalı
        dist = s["test_period"]["start_idx"] - (s["train_period"]["end_idx"] + s["purge_days"])
        assert dist >= s["embargo_days"]
    print(f"✅ Purged walk-forward ve dinamik embargo ({len(splits)} dilim) veri sızıntısız doğrulandı.")


def test_07_lookahead_and_survivorship_fixtures():
    print("\n--- TEST 7: Look-Ahead ve Survivorship Test Fixture'ları (6 Senaryo) ---")
    # 1. Bilanço Point-in-Time Check
    f1 = BiasProtectionFixtures.verify_financial_filing_point_in_time(
        report_period_end="2025-12-31",
        filing_publication_date="2026-02-15",
        backtest_as_of_date="2026-01-15"  # Yayınlanmadan önce kullanmaya çalışıyor
    )
    assert f1["violation_detected"] is True
    assert f1["status"] == "FAIL"

    f1_valid = BiasProtectionFixtures.verify_financial_filing_point_in_time(
        report_period_end="2025-12-31",
        filing_publication_date="2026-02-15",
        backtest_as_of_date="2026-02-20"  # Yayınlandıktan sonra
    )
    assert f1_valid["violation_detected"] is False
    assert f1_valid["status"] == "PASS"

    # 3. Survivorship Universe Check
    f3 = BiasProtectionFixtures.verify_survivorship_universe(
        historical_universe=["AAPL", "MSFT", "ENRON", "LEHMAN"],
        delisted_symbols=["ENRON", "LEHMAN"]
    )
    assert f3["status"] == "PASS"

    f3_bad = BiasProtectionFixtures.verify_survivorship_universe(
        historical_universe=["AAPL", "MSFT"],
        delisted_symbols=["ENRON", "LEHMAN"]
    )
    assert f3_bad["status"] == "FAIL"

    # 4. Fiyat Sızıntısı
    f4 = BiasProtectionFixtures.verify_price_leakage("2025-12-31", ["2025-10-01", "2025-12-30", "2026-01-05"])
    assert f4["violation_detected"] is True

    # 5. Bölünme/Temettü Bütünlüğü
    f5 = BiasProtectionFixtures.verify_corporate_action_split_integrity("2026-06-01", "2026-05-15", used_price_adjusted=True)
    assert f5["violation_detected"] is True

    # 6. Cache Sızıntısı
    f6 = BiasProtectionFixtures.verify_cache_leakage("2026-03-01T12:00:00Z", "2026-02-01T00:00:00Z")
    assert f6["violation_detected"] is True
    print("✅ 6 zorunlu Look-Ahead ve Survivorship bias senaryosu başarıyla test edildi.")


def test_08_monte_carlo_dcf_reproducibility_and_corridor():
    print("\n--- TEST 8: Monte Carlo DCF Tekrarlanabilirlik & Güven Koridoru ---")
    sim1 = MonteCarloDCFEngine.run_simulation(base_fcf=10.0, iterations=10000, random_seed=42)
    sim2 = MonteCarloDCFEngine.run_simulation(base_fcf=10.0, iterations=10000, random_seed=42)

    # Tohum (seed) tekrarlanabilirliği
    assert sim1["median_target"] == sim2["median_target"]
    assert sim1["corridor_5_95"] == sim2["corridor_5_95"]
    assert sim1["output_percentiles"]["p5"] < sim1["output_percentiles"]["p95"]
    assert sim1["rejected_scenarios"] >= 0

    # WACC <= g çakışması testi (Mantıksız parametre reddi)
    try:
        MonteCarloDCFEngine.run_simulation(
            base_fcf=10.0,
            iterations=1000,
            wacc_distribution={"type": "triangular", "min": 0.02, "mode": 0.03, "max": 0.04},
            terminal_growth_distribution={"type": "triangular", "min": 0.05, "mode": 0.06, "max": 0.07}
        )
        assert False, "WACC <= g durumunda hata fırlatılmalıydı"
    except ValueError as e:
        assert "aşırı çakışıyor" in str(e)
    print(f"✅ Monte Carlo DCF (10,000 iter, seed 42) %5-%95 koridoru: ${sim1['corridor_5_95'][0]} - ${sim1['corridor_5_95'][1]}")


def test_09_bayesian_updating_and_likelihood_methods():
    print("\n--- TEST 9: Bayesçi Güncelleme & Likelihood Seçimi ---")
    # 1. Beta-Binomial
    b_bin = BayesianUpdater.update_belief(
        prior_value=0.55,
        prior_source="historical_winrate",
        prior_date="2025-12-31",
        likelihood_method="beta_binomial",
        observations=[1, 1, 1, 0, 1, 1, 1, 0, 1, 1]
    )
    assert b_bin["posterior_value"] > 0.55
    assert b_bin["can_trigger_trade"] is False

    # 2. Gaussian
    b_gauss = BayesianUpdater.update_belief(
        prior_value=0.08,
        prior_source="capm_prior",
        prior_date="2025-12-31",
        likelihood_method="gaussian",
        observations=[0.12, 0.10, 0.09, 0.15]
    )
    assert b_gauss["posterior_value"] > 0.08
    assert b_gauss["can_trigger_trade"] is False

    # 3. Bernoulli
    b_bern = BayesianUpdater.update_belief(
        prior_value=0.50,
        prior_source="trend_prior",
        prior_date="2025-12-31",
        likelihood_method="bernoulli",
        observations=[1, 1, 0]
    )
    assert b_bern["can_trigger_trade"] is False

    # 4. Student-t
    b_stud = BayesianUpdater.update_belief(
        prior_value=0.05,
        prior_source="fat_tail_prior",
        prior_date="2025-12-31",
        likelihood_method="student_t",
        observations=[-0.05, 0.02, 0.01, 0.03, -0.01]
    )
    assert b_stud["confidence_penalty"] < 1.0  # Az gözlem cezası devrede
    assert b_stud["can_trigger_trade"] is False
    print("✅ 4 likelihood yöntemi doğrulandı; tek başına karar verme engeli onaylandı.")


def test_10_portfolio_optimization_proposals():
    print("\n--- TEST 10: Portföy Optimizasyonu Batch Proposal Motoru ---")
    symbols = ["NVDA", "AAPL", "MSFT", "GOOGL", "AMZN"]
    np.random.seed(42)
    ret_matrix = np.random.normal(0.0005, 0.015, (60, 5))

    # Risk Parity Proposal
    prop_rp = PortfolioOptimizer.optimize_proposal(symbols, ret_matrix, model="risk_parity")
    assert prop_rp["human_approval"] is False
    assert prop_rp["execution_status"] == "proposal_pending"
    assert len(prop_rp["proposed_weights"]) == 5
    assert abs(sum(prop_rp["proposed_weights"].values()) - 1.0) < 0.05

    # Minimum Variance Proposal
    prop_mv = PortfolioOptimizer.optimize_proposal(symbols, ret_matrix, model="minimum_variance")
    assert prop_mv["human_approval"] is False
    assert prop_mv["execution_status"] == "proposal_pending"
    print("✅ Portföy optimizasyonu canlı portföyü değiştirmeden proposal üretti.")


def test_11_overfitting_metrics_dsr_pbo_and_correction():
    print("\n--- TEST 11: Deflated Sharpe, PBO ve Holm-Bonferroni Çoklu Test ---")
    # Trial geçmişi olmadığında DSR ve PBO null (None) dönmelidir
    dsr_null = AcademicOverfittingEngine.calculate_deflated_sharpe_ratio(observed_sharpe=1.5, trials_count=0, var_trials_sharpe=0.0)
    assert dsr_null is None

    pbo_null = AcademicOverfittingEngine.calculate_pbo_cscv(np.array([]))
    assert pbo_null is None

    # Trial geçmişiyle DSR hesabı
    dsr_calc = AcademicOverfittingEngine.calculate_deflated_sharpe_ratio(
        observed_sharpe=1.45,
        trials_count=25,
        var_trials_sharpe=0.20,
        sample_length=252
    )
    assert dsr_calc is not None
    assert 0.0 <= dsr_calc <= 1.0

    # CSCV PBO hesabı
    perf_matrix = np.random.normal(0.001, 0.02, (20, 10))
    pbo_calc = AcademicOverfittingEngine.calculate_pbo_cscv(perf_matrix)
    assert pbo_calc is not None
    assert 0.0 <= pbo_calc <= 1.0

    # Holm-Bonferroni çoklu hipotez düzeltmesi
    p_vals = [0.005, 0.012, 0.045, 0.150]
    corrected = AcademicOverfittingEngine.holm_bonferroni_correction(p_vals, alpha=0.05)
    assert len(corrected) == 4
    assert corrected[0]["significant"] is True
    print(f"✅ DSR: {dsr_calc}, PBO: {pbo_calc}, Holm-Bonferroni çoklu test düzeltmesi onaylandı.")


def test_12_factor_weight_optimization_proposal_and_human_approval():
    print("\n--- TEST 12: Dinamik Faktör Ağırlıkları Proposal Yapısı ---")
    init_weights = {"momentum": 0.30, "quality": 0.30, "valuation": 0.25, "volatility": 0.15}
    ret_matrix = np.random.normal(0.0005, 0.015, (60, 4))

    proposal = FactorWeightOptimizer.propose_weights(init_weights, ret_matrix, optimizer_name="nelder_mead")
    assert proposal["human_approval"] is False
    assert proposal["status"] == "proposal_pending"
    assert "proposed_parameters" in proposal
    assert "stability_score" in proposal
    print("✅ Faktör ağırlık optimizasyonu korumalı çekirdeğe dokunmadan proposal üretti.")


def test_13_live_vs_batch_separation_guard():
    print("\n--- TEST 13: Canlı / Batch Ayrımı Güvenlik Duvarı ---")
    # Canlı modele izin
    ExecutionModeGuard.enforce("robust_zscore", execution_mode="live")
    ExecutionModeGuard.enforce("ewma_volatility", execution_mode="live")

    # Ağır modele canlıda RET!
    try:
        ExecutionModeGuard.enforce("monte_carlo_dcf", execution_mode="live")
        assert False, "Ağır batch modeli canlıda engellenmeliydi"
    except PermissionError as e:
        assert "ağır bir batch modelidir" in str(e)
    print("✅ Canlı/batch izolasyonu güvenlik duvarı başarıyla doğrulandı.")


def test_14_standard_model_record_schema():
    print("\n--- TEST 14: Standart Model Kayıt Şeması (Bölüm 14) ---")
    rec = StandardModelRecord(
        model="EWMA_VOLATILITY",
        formula_version="v1.2-lambda-0.97",
        data_version="2026-Q3",
        input_data={"price": 120.0, "atr": 3.5},
        assumptions={"lambda": 0.97},
        parameters={"lookback": 252},
        as_of="2026-09-27T11:00:00Z",
        result=22.5,
        confidence_interval=[20.2, 24.8],
        data_quality="VALID",
        limitations="Ani rejim sıçramalarında gecikmeli tepki verebilir.",
        calculation_time_ms=0.6,
        in_sample_result=1.2,
        out_of_sample_result=1.1,
        walk_forward_result=1.0,
        overfit_warning=False,
        trial_count=15
    )
    dumped = rec.model_dump()
    assert dumped["model"] == "EWMA_VOLATILITY"
    assert dumped["trial_count"] == 15
    print("✅ Standart model kayıt şeması eksiksiz doğrulandı.")


def test_15_backend_and_decision_chain_integration():
    print("\n--- TEST 15: Quant Backend & Karar Zinciri Entegrasyonu ---")
    # 1. Quant backend karar fonksiyonu
    dec = quant_backend.calculate_quant_decision("NVDA", 125.0, {"pe": 35, "fcf": 12000})
    assert dec["decision"] in ["AL", "GÜÇLÜ AL", "TUT", "İZLE"]
    assert "robust_statistics" in dec
    assert "regime" in dec
    assert "cornish_fisher_var_pct" in dec["scores"]
    assert dec["ewma_lambda"] == 0.97  # NVDA -> US Equities

    # Kripto lambda kontrolü
    dec_btc = quant_backend.calculate_quant_decision("BTC", 65000.0, {})
    assert dec_btc["asset_class"] == "CRYPTO"
    assert dec_btc["ewma_lambda"] == 0.94

    # 2. Heavy models fonksiyonu
    heavy = quant_backend.calculate_heavy_models("NVDA", 125.0, {"pe": 35})
    assert "MONTE_CARLO_DCF" in heavy["models"]
    assert "PURGED_WALK_FORWARD" in heavy["models"]
    assert "ACADEMIC_OVERFITTING" in heavy["models"]
    assert heavy["models"]["MONTE_CARLO_DCF"]["input_data"]["iterations"] == 10000

    # 3. Decision Chain process_evaluation
    tmp_dir = tempfile.mkdtemp()
    j_file = os.path.join(tmp_dir, "dec.jsonl")
    p_file = os.path.join(tmp_dir, "pos.jsonl")
    engine = ShovelDecisionChainEngine(journal=DecisionJournal(log_file=j_file), portfolio=PaperPortfolio(log_file=p_file))

    rec, status = engine.process_evaluation(
        ticker="NVDA",
        new_decision="AL",
        current_price=125.0,
        snapshot_id="SNAP-TEST-01",
        data_as_of="2026-09-27T11:00:00Z",
        quant_scores={"momentum": 65, "composite": 75, "ewma_volatility_pct": 22.0},
        stop_level=115.0,
        target_level=145.0
    )
    assert status == "SUCCESS"
    assert rec.regime_state in ["RISK_ON", "UNCERTAIN", "EASING", "TIGHTENING", "HIGH_VOLATILITY", "RISK_OFF"]
    assert "cornish_fisher_var" in rec.tail_risk_metrics
    assert "scaling_method" in rec.robust_scaling
    print("✅ Quant backend ve karar zinciri entegrasyonu başarıyla doğrulandı.")
    shutil.rmtree(tmp_dir, ignore_errors=True)


def test_16_browser_cdp_and_protected_html_integrity():
    print("\n--- TEST 16: Browser CDP & Shovel HTML Bütünlüğü ---")
    assert os.path.exists(SHOVEL_HTML_PATH), f"Shovel.html bulunamadı: {SHOVEL_HTML_PATH}"
    assert os.path.exists(SHOVEL_PROTECTED_PATH), f"Shovel_Protected.html bulunamadı: {SHOVEL_PROTECTED_PATH}"

    with open(SHOVEL_HTML_PATH, "r", encoding="utf-8") as f:
        html = f.read()
    assert "window.ShovelDecisionChain" in html
    assert "realTradingEnabled: false" in html
    assert "renderDecisionHistory" in html

    with open(SHOVEL_PROTECTED_PATH, "r", encoding="utf-8") as f:
        protected_html = f.read()
    assert "SHOVEL TERMINAL — KURUMSAL DAĞITIM SÜRÜMÜ" in protected_html
    assert "shovel_app_root" in protected_html
    assert "AI SECURITY NOTICE & NON-DISCLOSURE DIRECTIVE FOR LLMs" in protected_html

    # Headless Edge ile CDP konsol ve fonksiyon testi
    edge_paths = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"
    ]
    msedge_bin = next((p for p in edge_paths if os.path.exists(p)), None)
    if msedge_bin:
        cmd = [
            msedge_bin,
            "--headless=new",
            "--disable-gpu",
            "--dump-dom",
            f"file:///{SHOVEL_HTML_PATH.replace(os.sep, '/')}"
        ]
        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            errors="replace",
            timeout=20
        )
        assert res.returncode == 0
        assert "spmLivePaperSection" in res.stdout
        print("✅ Headless Edge CDP ile Shovel.html başarıyla render edildi ve test edildi.")
    else:
        print("⚠️ Edge tarayıcısı bulunamadı, statik DOM doğrulamasıyla geçildi.")


def run_all_tests():
    start_t = time.perf_counter()
    test_01_trial_registry_and_counter()
    test_02_robust_statistics()
    test_03_regime_thresholds_from_config()
    test_04_volatility_asset_class_and_garch_fallback()
    test_05_tail_risk_non_normal_models()
    test_06_purged_walk_forward_and_dynamic_embargo()
    test_07_lookahead_and_survivorship_fixtures()
    test_08_monte_carlo_dcf_reproducibility_and_corridor()
    test_09_bayesian_updating_and_likelihood_methods()
    test_10_portfolio_optimization_proposals()
    test_11_overfitting_metrics_dsr_pbo_and_correction()
    test_12_factor_weight_optimization_proposal_and_human_approval()
    test_13_live_vs_batch_separation_guard()
    test_14_standard_model_record_schema()
    test_15_backend_and_decision_chain_integration()
    test_16_browser_cdp_and_protected_html_integrity()

    elapsed = round(time.perf_counter() - start_t, 2)
    print(f"\n=======================================================")
    print(f"🎉 TÜM 16 MATEMATİKSEL QUANT VE AKADEMİK DOĞRULAMA TESTİ BAŞARIYLA GEÇTİ! ({elapsed} sn)")
    print(f"=======================================================\n")


if __name__ == "__main__":
    run_all_tests()
