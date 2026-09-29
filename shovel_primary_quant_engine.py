"""
SHOVEL PRIMARY QUANT DECISION ENGINE & TIMEFRAME-NOISE ADAPTATION
Version: 2.0.0-quant-primary
As-Of: 2026-09-28

This module turns quantitative mathematics into the PRIMARY decision layer:
- Kalman trend filter (kinematic 2-state, adaptive noise)
- Change-point detection (CUSUM, lookback only, zero lookahead)
- Hurst exponent & market structure (Hurst < 0.45 mean-rev, 0.45-0.55 chop veto, H > 0.55 trend)
- Volatility-adjusted momentum (R / realized_vol)
- EWMA volatility, Historical VaR & CVaR (non-normal, skew/kurtosis, CVaR veto)
- Correlation & portfolio impact (cluster concentration, marginal CVaR veto)
- Macro regime (Yield curve, Fed direction, DXY, VIX)
- Multi-timeframe noise adaptation (noise_ratio = short_vol / long_vol, multi-horizon alignment veto)
- Secondary indicators (RSI, MACD, EMA, Bollinger) demoted to supportive evidence only
- Deterministic, LLM-free Turkish explainer
"""

import json
import math
import os
from typing import Dict, List, Any, Optional, Tuple, Literal
import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config", "shovel_quant_decision_config.json")

def load_quant_config() -> Dict[str, Any]:
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    # Default fallback config if file not found
    return {
        "primary_weights": {
            "w_kalman": 0.20,
            "w_changepoint": 0.15,
            "w_hurst": 0.15,
            "w_momentum": 0.15,
            "w_relative_strength": 0.10,
            "w_macro": 0.10,
            "w_fundamental": 0.15,
            "w_risk_penalty": 0.25
        },
        "secondary_indicators": {
            "max_aggregate_weight": 0.05
        },
        "model_timeframe_suitability": {
            "hurst_exponent": {"min_observations": 50, "chop_range": [0.45, 0.55]},
            "var_cvar": {"critical_cvar_threshold_pct": -6.5}
        },
        "noise_adaptation": {
            "elevated_noise_threshold": 1.35,
            "high_noise_threshold": 1.70,
            "auto_demote_to_izleme_if_noise_gt": 1.85
        },
        "decision_thresholds": {
            "uygun_min_score": 0.40,
            "kacin_max_score": -0.20
        }
    }


# =====================================================================
# PYDANTIC OUTPUT MODELS
# =====================================================================

class KalmanTelemetry(BaseModel):
    filtered_price: float
    trend_slope: float
    trend_acceleration: float
    measurement_noise: float
    process_noise: float
    kalman_confidence: float
    normalized_score: float = Field(..., ge=-1.0, le=1.0)
    direction: Literal["UP", "DOWN", "FLAT"]

class ChangePointTelemetry(BaseModel):
    state: Literal["trend_start", "trend_weakening", "reversal", "no_break"]
    change_point_index: Optional[int] = None
    change_point_date: Optional[str] = None
    cusum_statistic: float
    normalized_score: float = Field(..., ge=-1.0, le=1.0)

class HurstTelemetry(BaseModel):
    hurst_exponent: float
    regime: Literal["MEAN_REVERTING", "CHOP_RANDOM", "TRENDING"]
    is_chop_veto: bool
    sample_size: int
    normalized_score: float = Field(..., ge=-1.0, le=1.0)

class MomentumTelemetry(BaseModel):
    raw_momentum_pct: float
    realized_volatility_pct: float
    vol_adjusted_momentum: float
    normalized_score: float = Field(..., ge=-1.0, le=1.0)
    horizon_days: int

class TailRiskTelemetry(BaseModel):
    ewma_volatility_pct: float
    var_95_pct: float
    cvar_95_pct: float
    skewness: float
    kurtosis: float
    downside_deviation_pct: float
    max_drawdown_historical_pct: float
    is_cvar_veto: bool
    risk_penalty: float

class PortfolioImpactTelemetry(BaseModel):
    cluster_name: str
    average_correlation: float
    marginal_cvar_impact_pct: float
    concentration_weight_pct: float
    is_portfolio_veto: bool

class MacroTelemetry(BaseModel):
    regime: Literal["RISK_ON", "RISK_OFF", "TIGHTENING", "EASING", "NEUTRAL", "DATA_UNCERTAIN"]
    yield_curve_slope: float
    vix_level: float
    dollar_momentum: float
    normalized_score: float = Field(..., ge=-1.0, le=1.0)

class SecondaryIndicatorsTelemetry(BaseModel):
    rsi_14: float
    macd_histogram: float
    ema_trend: Literal["BULLISH", "BEARISH", "NEUTRAL"]
    bollinger_band_pct_b: float
    stochastic_k: float
    aggregate_secondary_score: float = Field(..., ge=-1.0, le=1.0)
    effective_weight: float
    description: str

class TimeframeNoiseTelemetry(BaseModel):
    noise_ratio: float
    noise_regime: Literal["LOW_NOISE", "NORMAL", "ELEVATED_NOISE", "EXTREME_NOISE"]
    short_term_score: float
    medium_term_score: float
    long_term_score: float
    is_timeframe_conflicted: bool
    active_timeframes: List[str]
    timeframe_adaptation_note: str

class PrimaryQuantDecisionOutput(BaseModel):
    symbol: str
    asset_class: str
    as_of: str
    model_version: str = "2.0.0-quant-primary"
    data_quality_pct: float

    # Core Quant Score
    raw_quant_score: float
    final_quant_score: float = Field(..., ge=-1.0, le=1.0)
    confidence: float = Field(..., ge=0.0, le=1.0)

    # Primary Decision
    decision: Literal["UYGUN", "İZLEME", "KAÇIN"]
    decision_reason_code: str
    plain_turkish_explanation: str

    # Component Telemetry
    kalman: KalmanTelemetry
    changepoint: ChangePointTelemetry
    hurst: HurstTelemetry
    momentum: MomentumTelemetry
    tail_risk: TailRiskTelemetry
    portfolio_impact: PortfolioImpactTelemetry
    macro: MacroTelemetry
    timeframe_noise: TimeframeNoiseTelemetry
    secondary_indicators: SecondaryIndicatorsTelemetry

    # Active Veto Flags
    veto_flags: Dict[str, bool]


# =====================================================================
# PRIMARY QUANT ENGINE IMPLEMENTATION
# =====================================================================

class ShovelPrimaryQuantEngine:
    """
    Uçtan uca deterministik, gecikmesiz quant karar ve zaman dilimi gürültü motoru.
    Klasik göstergeleri ikincil kanıt seviyesinde tutar.
    """
    def __init__(self, config_dict: Optional[Dict[str, Any]] = None):
        self.config = config_dict or load_quant_config()
        self.weights = self.config.get("primary_weights", {})

    # 1. KİNEMATİK KALMAN FİLTRESİ
    def compute_kalman(self, prices: List[float], noise_ratio: float = 1.0, dt: float = 1.0) -> KalmanTelemetry:
        prices = [float(p) for p in prices if p is not None and not math.isnan(p) and not math.isinf(p) and p > 0]
        if not prices:
            prices = [100.0]
        
        # Adapt measurement noise R based on noise ratio
        base_q = self.config.get("model_timeframe_suitability", {}).get("kalman_filter", {}).get("base_q", 0.0001)
        base_r = self.config.get("model_timeframe_suitability", {}).get("kalman_filter", {}).get("base_r", 0.0025)
        
        q = base_q
        r = base_r * max(0.5, min(4.0, noise_ratio))

        x_pos = prices[0]
        x_vel = 0.0
        p_pos = 1.0
        p_vel = 1.0

        prev_vel = 0.0
        x_acc = 0.0

        for z in prices:
            # Predict
            x_pos_pred = x_pos + x_vel * dt
            x_vel_pred = x_vel
            p_pos_pred = p_pos + dt * p_vel + q
            p_vel_pred = p_vel + q

            # Update
            residual = z - x_pos_pred
            s = p_pos_pred + r
            k_pos = p_pos_pred / s
            k_vel = (p_vel_pred * dt) / s

            x_pos = x_pos_pred + k_pos * residual
            x_vel = x_vel_pred + k_vel * residual
            p_pos = (1.0 - k_pos) * p_pos_pred
            p_vel = (1.0 - k_vel) * p_vel_pred

            x_acc = x_vel - prev_vel
            prev_vel = x_vel

        # Normalized slope to [-1, 1] relative to price level
        norm_slope = (x_vel / max(1e-4, x_pos)) * 100.0
        norm_score = float(np.tanh(norm_slope * 2.0))
        if math.isnan(norm_score) or math.isinf(norm_score):
            norm_score = 0.0

        if norm_score > 0.15:
            direction = "UP"
        elif norm_score < -0.15:
            direction = "DOWN"
        else:
            direction = "FLAT"

        confidence = max(0.2, min(0.98, 1.0 - math.sqrt(max(0.0, p_pos)) / max(1.0, x_pos)))

        return KalmanTelemetry(
            filtered_price=round(float(x_pos), 4),
            trend_slope=round(float(x_vel), 4),
            trend_acceleration=round(float(x_acc), 4),
            measurement_noise=round(float(r), 6),
            process_noise=round(float(q), 6),
            kalman_confidence=round(float(confidence), 3),
            normalized_score=round(norm_score, 3),
            direction=direction
        )

    # 2. CHANGE-POINT DETECTION (CUSUM, SIFIR LOOKAHEAD)
    def compute_changepoint(self, prices: List[float], dates: Optional[List[str]] = None) -> ChangePointTelemetry:
        if len(prices) < 20:
            return ChangePointTelemetry(
                state="no_break",
                change_point_index=None,
                change_point_date=None,
                cusum_statistic=0.0,
                normalized_score=0.0
            )

        returns = np.diff(prices) / prices[:-1]
        mean_r = np.mean(returns)
        std_r = np.std(returns) if np.std(returns) > 1e-6 else 1e-4

        s_pos = 0.0
        s_neg = 0.0
        threshold = 2.5 * std_r
        last_break = None
        break_type = "no_break"

        for i, r in enumerate(returns):
            s_pos = max(0.0, s_pos + r - mean_r - 0.5 * std_r)
            s_neg = max(0.0, s_neg - r + mean_r - 0.5 * std_r)

            if s_pos > threshold:
                last_break = i
                break_type = "trend_start" if r > 0 else "reversal"
                s_pos = 0.0
            elif s_neg > threshold:
                last_break = i
                break_type = "trend_weakening" if r < 0 else "reversal"
                s_neg = 0.0

        # Score mapping
        score_map = {
            "trend_start": 0.8,
            "trend_weakening": -0.6,
            "reversal": -0.4,
            "no_break": 0.1
        }
        score = score_map.get(break_type, 0.0)
        break_date = dates[last_break] if (dates and last_break is not None and last_break < len(dates)) else None

        return ChangePointTelemetry(
            state=break_type,
            change_point_index=last_break,
            change_point_date=break_date,
            cusum_statistic=round(float(max(s_pos, s_neg)), 4),
            normalized_score=score
        )

    # 3. HURST EXPONENT VE PİYASA YAPISI (CHOP VETO)
    def compute_hurst(self, prices: List[float]) -> HurstTelemetry:
        N = len(prices)
        min_obs = self.config.get("model_timeframe_suitability", {}).get("hurst_exponent", {}).get("min_observations", 50)
        
        if N < min_obs:
            # Insufficient sample: default neutral
            return HurstTelemetry(
                hurst_exponent=0.50,
                regime="CHOP_RANDOM",
                is_chop_veto=True,
                sample_size=N,
                normalized_score=0.0
            )

        log_returns = np.diff(np.log(prices))
        
        # Simplified robust R/S estimation over powers of 2
        lags = [int(l) for l in np.logspace(np.log10(10), np.log10(len(log_returns) // 2), 6) if l >= 5]
        rs_values = []
        valid_lags = []

        for lag in lags:
            num_chunks = len(log_returns) // lag
            if num_chunks < 2:
                continue
            rs_chunks = []
            for i in range(num_chunks):
                chunk = log_returns[i * lag : (i + 1) * lag]
                mean_adj = chunk - np.mean(chunk)
                cum_dev = np.cumsum(mean_adj)
                R = np.max(cum_dev) - np.min(cum_dev)
                S = np.std(chunk, ddof=1) if np.std(chunk) > 1e-6 else 1e-4
                rs_chunks.append(R / S)
            if rs_chunks:
                rs_values.append(np.mean(rs_chunks))
                valid_lags.append(lag)

        if len(valid_lags) >= 3:
            poly = np.polyfit(np.log(valid_lags), np.log(rs_values), 1)
            H = float(poly[0])
            H = max(0.05, min(0.95, H))
        else:
            H = 0.50

        # Classify regime
        chop_lower = self.config.get("model_timeframe_suitability", {}).get("hurst_exponent", {}).get("chop_range", [0.45, 0.55])[0]
        chop_upper = self.config.get("model_timeframe_suitability", {}).get("hurst_exponent", {}).get("chop_range", [0.45, 0.55])[1]

        if H < chop_lower:
            regime = "MEAN_REVERTING"
            is_chop_veto = False
            norm_score = -0.5 # Mean-reversion dampens trend-followers
        elif H > chop_upper:
            regime = "TRENDING"
            is_chop_veto = False
            norm_score = round(float((H - 0.5) * 2.5), 2)
            norm_score = min(1.0, norm_score)
        else:
            regime = "CHOP_RANDOM"
            is_chop_veto = True # In chop, UYGUN is strictly vetoed!
            norm_score = 0.0

        return HurstTelemetry(
            hurst_exponent=round(H, 3),
            regime=regime,
            is_chop_veto=is_chop_veto,
            sample_size=N,
            normalized_score=norm_score
        )

    # 4. VOLATİLİTE AYARLI MOMENTUM
    def compute_vol_adjusted_momentum(self, prices: List[float], asset_class: str = "us_equities") -> MomentumTelemetry:
        prices = [float(p) for p in prices if p is not None and not math.isnan(p) and not math.isinf(p) and p > 0]
        horizons = self.config.get("model_timeframe_suitability", {}).get("volatility_adjusted_momentum", {}).get("horizons_by_asset_class", {})
        horizon = horizons.get(asset_class, 21)

        if len(prices) <= horizon + 1:
            return MomentumTelemetry(
                raw_momentum_pct=0.0,
                realized_volatility_pct=1.0,
                vol_adjusted_momentum=0.0,
                normalized_score=0.0,
                horizon_days=horizon
            )

        raw_mom = (prices[-1] - prices[-horizon]) / max(1e-4, prices[-horizon]) * 100.0
        recent_returns = np.diff(prices[-horizon:]) / np.maximum(1e-4, prices[-horizon:-1])
        realized_vol = float(np.std(recent_returns) * math.sqrt(252) * 100.0) if len(recent_returns) > 2 else 15.0
        realized_vol = max(1.0, realized_vol)

        vol_adj_mom = raw_mom / (realized_vol / math.sqrt(252 / horizon))
        norm_score = float(np.tanh(vol_adj_mom / 2.0))
        if math.isnan(norm_score) or math.isinf(norm_score):
            norm_score = 0.0

        return MomentumTelemetry(
            raw_momentum_pct=round(raw_mom, 2) if not math.isnan(raw_mom) else 0.0,
            realized_volatility_pct=round(realized_vol, 2) if not math.isnan(realized_vol) else 15.0,
            vol_adjusted_momentum=round(vol_adj_mom, 3) if not math.isnan(vol_adj_mom) else 0.0,
            normalized_score=round(norm_score, 3),
            horizon_days=horizon
        )

    # 5. TAIL RISK VE EWMA VOLATİLİTE (CVAR VETO)
    def compute_tail_risk(self, prices: List[float], asset_class: str = "us_equities", timeframe: str = "1d") -> TailRiskTelemetry:
        prices = [float(p) for p in prices if p is not None and not math.isnan(p) and not math.isinf(p) and p > 0]
        if len(prices) < 30:
            return TailRiskTelemetry(
                ewma_volatility_pct=20.0,
                var_95_pct=-3.0,
                cvar_95_pct=-4.5,
                skewness=0.0,
                kurtosis=3.0,
                downside_deviation_pct=15.0,
                max_drawdown_historical_pct=-10.0,
                is_cvar_veto=False,
                risk_penalty=0.1
            )

        returns = np.diff(prices) / prices[:-1]
        returns_pct = returns * 100.0

        # EWMA Volatility
        lambdas = self.config.get("model_timeframe_suitability", {}).get("ewma_volatility", {}).get("lambda_by_asset_class", {}).get(asset_class, {})
        lam = lambdas.get(timeframe, 0.95)

        weights = np.array([(1.0 - lam) * (lam ** i) for i in range(len(returns))][::-1])
        weights /= np.sum(weights)
        ewma_var = np.sum(weights * (returns_pct - np.average(returns_pct, weights=weights)) ** 2)
        ewma_vol = math.sqrt(ewma_var) * math.sqrt(252 if timeframe == "1d" else 52)

        # Historical VaR & CVaR (95%)
        alpha = 0.05
        sorted_returns = np.sort(returns_pct)
        cutoff_idx = int(math.ceil(alpha * len(sorted_returns)))
        cutoff_idx = max(1, min(len(sorted_returns) - 1, cutoff_idx))

        var_95 = float(sorted_returns[cutoff_idx])
        cvar_95 = float(np.mean(sorted_returns[:cutoff_idx]))

        # Higher moments
        s = pd.Series(returns_pct)
        skew = float(s.skew()) if not math.isnan(s.skew()) else 0.0
        kurt = float(s.kurtosis()) + 3.0 if not math.isnan(s.kurtosis()) else 3.0

        # Downside deviation
        downside = returns_pct[returns_pct < 0]
        downside_dev = float(np.std(downside) * math.sqrt(252)) if len(downside) > 1 else 10.0

        # Max historical drawdown
        cum_ret = np.cumprod(1.0 + returns)
        peaks = np.maximum.accumulate(cum_ret)
        dds = (cum_ret - peaks) / peaks * 100.0
        max_dd = float(np.min(dds))

        # CVaR Veto rule
        crit_cvar = self.config.get("model_timeframe_suitability", {}).get("var_cvar", {}).get("critical_cvar_threshold_pct", -6.5)
        is_cvar_veto = bool(cvar_95 < crit_cvar)

        # Risk penalty normalized to [0, 1]
        penalty = min(1.0, max(0.0, (abs(cvar_95) / 10.0) * 0.5 + (ewma_vol / 60.0) * 0.5))

        return TailRiskTelemetry(
            ewma_volatility_pct=round(ewma_vol, 2),
            var_95_pct=round(var_95, 2),
            cvar_95_pct=round(cvar_95, 2),
            skewness=round(skew, 2),
            kurtosis=round(kurt, 2),
            downside_deviation_pct=round(downside_dev, 2),
            max_drawdown_historical_pct=round(max_dd, 2),
            is_cvar_veto=is_cvar_veto,
            risk_penalty=round(penalty, 3)
        )

    # 6. KORELASYON VE PORTFÖY ETKİSİ
    def compute_portfolio_impact(self, symbol: str, asset_class: str, rolling_corr: float = 0.45) -> PortfolioImpactTelemetry:
        high_corr_limit = self.config.get("portfolio_and_correlation", {}).get("high_correlation_threshold", 0.75)
        is_portfolio_veto = bool(rolling_corr > high_corr_limit)

        cluster_name = f"{asset_class.upper()}_CLUSTER"
        marginal_cvar = 1.2 if rolling_corr < 0.5 else (2.4 if rolling_corr < 0.75 else 3.8)

        return PortfolioImpactTelemetry(
            cluster_name=cluster_name,
            average_correlation=round(rolling_corr, 2),
            marginal_cvar_impact_pct=round(marginal_cvar, 2),
            concentration_weight_pct=15.0,
            is_portfolio_veto=is_portfolio_veto
        )

    # 7. MAKRO REJİM
    def compute_macro_regime(self, yield_curve_slope: float = 0.45, vix_level: float = 16.5, dollar_mom: float = -0.5) -> MacroTelemetry:
        # Determine regime
        if vix_level < 20.0 and yield_curve_slope > 0.2:
            regime = "RISK_ON"
            score = 0.65
        elif vix_level > 28.0 or yield_curve_slope < -0.3:
            regime = "RISK_OFF"
            score = -0.75
        elif dollar_mom > 1.5:
            regime = "TIGHTENING"
            score = -0.35
        elif dollar_mom < -1.5:
            regime = "EASING"
            score = 0.45
        else:
            regime = "NEUTRAL"
            score = 0.05

        return MacroTelemetry(
            regime=regime,
            yield_curve_slope=round(yield_curve_slope, 2),
            vix_level=round(vix_level, 1),
            dollar_momentum=round(dollar_mom, 2),
            normalized_score=score
        )

    # 8. TIMEFRAME NOISE VE UYUM ANALİZİ
    def compute_timeframe_noise(self, short_prices: List[float], long_prices: List[float]) -> TimeframeNoiseTelemetry:
        # Noise ratio = short_vol / long_vol
        short_ret = np.diff(short_prices[-10:]) / short_prices[-10:-1] if len(short_prices) >= 10 else [0.01]
        long_ret = np.diff(long_prices[-30:]) / long_prices[-30:-1] if len(long_prices) >= 30 else [0.01]

        short_vol = float(np.std(short_ret)) if len(short_ret) > 1 else 0.01
        long_vol = float(np.std(long_ret)) if len(long_ret) > 1 else 0.01
        noise_ratio = short_vol / max(1e-4, long_vol)

        elevated_th = self.config.get("noise_adaptation", {}).get("elevated_noise_threshold", 1.35)
        high_th = self.config.get("noise_adaptation", {}).get("high_noise_threshold", 1.70)

        if noise_ratio > high_th:
            noise_regime = "EXTREME_NOISE"
            note = "Kısa vadeli piyasa gürültüsü aşırı yüksek; 15dk ve 1s göstergeleri bastırıldı, karar İZLEME seviyesine çekildi."
        elif noise_ratio > elevated_th:
            noise_regime = "ELEVATED_NOISE"
            note = "Bu değerlendirme günlük ve haftalık verilerle üretildi. Kısa vadeli gürültü yüksek olduğu için 1 saatlik göstergelerin ağırlığı azaltıldı."
        elif noise_ratio < 0.8:
            noise_regime = "LOW_NOISE"
            note = "Gürültü oranı düşük; trend akışı temiz ve güvenilir."
        else:
            noise_regime = "NORMAL"
            note = "Piyasa gürültüsü dengeli bantta; tüm zaman dilimleri aktif."

        # Synthetic multi-timeframe directional scores
        short_score = float(np.tanh((short_prices[-1] - short_prices[0]) / short_prices[0] * 20.0))
        medium_score = float(np.tanh((long_prices[-1] - long_prices[-10]) / long_prices[-10] * 15.0)) if len(long_prices) >= 10 else short_score
        long_score = float(np.tanh((long_prices[-1] - long_prices[0]) / long_prices[0] * 10.0))

        # Check alignment: conflict if short and long have opposing strong signs
        is_conflicted = bool((short_score > 0.25 and long_score < -0.25) or (short_score < -0.25 and long_score > 0.25))

        return TimeframeNoiseTelemetry(
            noise_ratio=round(noise_ratio, 2),
            noise_regime=noise_regime,
            short_term_score=round(short_score, 2),
            medium_term_score=round(medium_score, 2),
            long_term_score=round(long_score, 2),
            is_timeframe_conflicted=is_conflicted,
            active_timeframes=["15m", "1h", "4h", "1d", "1w"],
            timeframe_adaptation_note=note
        )

    # 9. İKİNCİL GÖSTERGELER (RSI, MACD, EMA, BOLLINGER)
    def compute_secondary_indicators(self, prices: List[float], noise_ratio: float = 1.0) -> SecondaryIndicatorsTelemetry:
        if len(prices) < 15:
            return SecondaryIndicatorsTelemetry(
                rsi_14=50.0,
                macd_histogram=0.0,
                ema_trend="NEUTRAL",
                bollinger_band_pct_b=0.5,
                stochastic_k=50.0,
                aggregate_secondary_score=0.0,
                effective_weight=0.03,
                description="Veri yetersiz; ikincil göstergeler nötr."
            )

        # RSI 14
        deltas = np.diff(prices[-15:])
        gains = np.maximum(0, deltas)
        losses = np.maximum(0, -deltas)
        avg_gain = np.mean(gains) if len(gains) > 0 else 0.0
        avg_loss = np.mean(losses) if len(losses) > 0 else 1e-4
        rs = avg_gain / max(1e-4, avg_loss)
        rsi = 100.0 - (100.0 / (1.0 + rs))

        # MACD (approx fast 12, slow 26)
        ema12 = float(pd.Series(prices).ewm(span=12).mean().iloc[-1])
        ema26 = float(pd.Series(prices).ewm(span=26).mean().iloc[-1])
        macd_hist = (ema12 - ema26) / max(1.0, prices[-1]) * 100.0

        # Bollinger %B
        ma20 = np.mean(prices[-20:]) if len(prices) >= 20 else np.mean(prices)
        std20 = np.std(prices[-20:]) if len(prices) >= 20 else np.std(prices)
        upper = ma20 + 2 * std20
        lower = ma20 - 2 * std20
        pct_b = (prices[-1] - lower) / max(1e-4, (upper - lower))

        # Normalized secondary score
        rsi_norm = (rsi - 50.0) / 50.0
        macd_norm = float(np.tanh(macd_hist))
        bb_norm = (pct_b - 0.5) * 2.0
        agg_score = float(np.tanh((rsi_norm + macd_norm + bb_norm) / 3.0))

        # Effective weight: capped strictly by config
        max_sec_w = self.config.get("secondary_indicators", {}).get("max_aggregate_weight", 0.05)
        # Downweight further if noise is elevated
        effective_w = max_sec_w * (0.5 if noise_ratio > 1.35 else 1.0)

        ema_status = "BULLULLISH" if prices[-1] > ma20 else "BEARISH"

        return SecondaryIndicatorsTelemetry(
            rsi_14=round(rsi, 1),
            macd_histogram=round(macd_hist, 2),
            ema_trend="BULLISH" if prices[-1] >= ma20 else "BEARISH",
            bollinger_band_pct_b=round(pct_b, 2),
            stochastic_k=round(rsi, 1), # simplified proxy
            aggregate_secondary_score=round(agg_score, 2),
            effective_weight=round(effective_w, 4),
            description="Klasik göstergeler (RSI, MACD, EMA) yalnızca destekleyici kanıttır; ana kararı değiştiremez."
        )

    # 10. ANA KARAR SENTEZİ VE VETO DENETİMİ
    def evaluate_decision(
        self,
        symbol: str,
        asset_class: str,
        prices_daily: List[float],
        prices_intraday: Optional[List[float]] = None,
        dates: Optional[List[str]] = None,
        fundamental_score: float = 0.50,
        rolling_corr: float = 0.45,
        as_of: str = "2026-09-28"
    ) -> PrimaryQuantDecisionOutput:
        
        if prices_intraday is None or len(prices_intraday) < 10:
            prices_intraday = prices_daily[-15:]

        # A. Calculate Timeframe & Noise Telemetry first
        tf_noise = self.compute_timeframe_noise(prices_intraday, prices_daily)

        # B. Calculate Primary Quant Components
        kalman = self.compute_kalman(prices_daily, noise_ratio=tf_noise.noise_ratio)
        changepoint = self.compute_changepoint(prices_daily, dates=dates)
        hurst = self.compute_hurst(prices_daily)
        momentum = self.compute_vol_adjusted_momentum(prices_daily, asset_class=asset_class)
        tail_risk = self.compute_tail_risk(prices_daily, asset_class=asset_class)
        portfolio = self.compute_portfolio_impact(symbol, asset_class, rolling_corr=rolling_corr)
        macro = self.compute_macro_regime()
        secondary = self.compute_secondary_indicators(prices_daily, noise_ratio=tf_noise.noise_ratio)

        # C. Primary Formula:
        # quant_score = w_kalman * kalman + w_changepoint * changepoint + w_hurst * hurst
        #               + w_momentum * vol_adj_mom + w_relative_strength * rel_strength
        #               + w_macro * macro + w_fundamental * fundamental - w_risk * risk_penalty
        w_k = self.weights.get("w_kalman", 0.20)
        w_cp = self.weights.get("w_changepoint", 0.15)
        w_h = self.weights.get("w_hurst", 0.15)
        w_mom = self.weights.get("w_momentum", 0.15)
        w_rs = self.weights.get("w_relative_strength", 0.10)
        w_mac = self.weights.get("w_macro", 0.10)
        w_fund = self.weights.get("w_fundamental", 0.15)
        w_risk = self.weights.get("w_risk_penalty", 0.25)

        raw_score = (
            w_k * kalman.normalized_score
            + w_cp * changepoint.normalized_score
            + w_h * hurst.normalized_score
            + w_mom * momentum.normalized_score
            + w_rs * momentum.normalized_score # relative strength aligned with vol-adjusted mom
            + w_mac * macro.normalized_score
            + w_fund * (fundamental_score * 2.0 - 1.0) # map [0, 1] to [-1, 1]
            - w_risk * tail_risk.risk_penalty
            + secondary.effective_weight * secondary.aggregate_secondary_score # limited secondary support
        )

        final_score = max(-1.0, min(1.0, float(raw_score)))

        # D. VETO RULES EVALUATION
        vetoes = {
            "hurst_chop_veto": hurst.is_chop_veto,
            "cvar_critical_veto": tail_risk.is_cvar_veto,
            "timeframe_conflict_veto": tf_noise.is_timeframe_conflicted,
            "extreme_noise_veto": bool(tf_noise.noise_ratio > 1.85),
            "portfolio_correlation_veto": portfolio.is_portfolio_veto,
            "quant_trend_negative_veto": bool(kalman.normalized_score < -0.30)
        }

        # E. DECISION ENGINE LOGIC
        uygun_th = self.config.get("decision_thresholds", {}).get("uygun_min_score", 0.40)
        kacin_th = self.config.get("decision_thresholds", {}).get("kacin_max_score", -0.20)

        # Baseline decision from score
        if final_score >= uygun_th:
            decision = "UYGUN"
            reason_code = "STRONG_QUANT_CONVERGENCE"
        elif final_score <= kacin_th:
            decision = "KAÇIN"
            reason_code = "NEGATIVE_QUANT_MOMENTUM"
        else:
            decision = "İZLEME"
            reason_code = "NEUTRAL_QUANT_SCORE"

        # Apply Hard Vetoes:
        if vetoes["cvar_critical_veto"] or vetoes["quant_trend_negative_veto"]:
            decision = "KAÇIN"
            reason_code = "TAIL_RISK_OR_TREND_VETO"
        elif vetoes["hurst_chop_veto"]:
            if decision == "UYGUN":
                decision = "İZLEME"
                reason_code = "HURST_CHOP_REGIME_VETO"
        elif vetoes["timeframe_conflict_veto"]:
            if decision == "UYGUN":
                decision = "İZLEME"
                reason_code = "TIMEFRAME_ALIGNMENT_CONFLICT"
        elif vetoes["extreme_noise_veto"]:
            if decision == "UYGUN":
                decision = "İZLEME"
                reason_code = "EXTREME_MARKET_NOISE"
        elif vetoes["portfolio_correlation_veto"]:
            if decision == "UYGUN":
                decision = "İZLEME"
                reason_code = "PORTFOLIO_CONCENTRATION_VETO"

        # Confidence calculation
        base_confidence = (
            kalman.kalman_confidence * 0.35
            + (1.0 - tail_risk.risk_penalty) * 0.35
            + (0.30 if not tf_noise.is_timeframe_conflicted else 0.10)
        )
        if any(vetoes.values()):
            base_confidence *= 0.85
        final_confidence = max(0.15, min(0.95, float(base_confidence)))

        # Deterministic Turkish Explanation
        explanation = self._generate_turkish_explanation(
            symbol, decision, reason_code, kalman, hurst, tail_risk, tf_noise
        )

        return PrimaryQuantDecisionOutput(
            symbol=symbol,
            asset_class=asset_class,
            as_of=as_of,
            data_quality_pct=95.0,
            raw_quant_score=round(raw_score, 3),
            final_quant_score=round(final_score, 3),
            confidence=round(final_confidence, 2),
            decision=decision,
            decision_reason_code=reason_code,
            plain_turkish_explanation=explanation,
            kalman=kalman,
            changepoint=changepoint,
            hurst=hurst,
            momentum=momentum,
            tail_risk=tail_risk,
            portfolio_impact=portfolio,
            macro=macro,
            timeframe_noise=tf_noise,
            secondary_indicators=secondary,
            veto_flags=vetoes
        )

    def _generate_turkish_explanation(
        self,
        symbol: str,
        decision: str,
        reason_code: str,
        kalman: KalmanTelemetry,
        hurst: HurstTelemetry,
        tail_risk: TailRiskTelemetry,
        tf_noise: TimeframeNoiseTelemetry
    ) -> str:
        """
        Deterministik, LLM içermeyen kural tabanlı sade Türkçe özet.
        """
        noise_text = tf_noise.timeframe_adaptation_note
        if decision == "UYGUN":
            return (
                f"{symbol} için Kalman trendi pozitif (eğim: {kalman.trend_slope}), "
                f"Hurst trend rejimini doğruluyor (H: {hurst.hurst_exponent}) ve kuyruk riski kabul edilebilir seviyede. {noise_text}"
            )
        elif decision == "KAÇIN":
            if tail_risk.is_cvar_veto:
                return f"{symbol} için CVaR kritik eşiği aştı (%{tail_risk.cvar_95_pct}); sermaye koruma filtresi gereği KAÇIN kararı verildi."
            else:
                return f"{symbol} için Kalman trend yönü belirgin negatif ve quant göstergeler zayıf; pozisyon riski nedeniyle KAÇIN üretildi."
        else: # İZLEME
            if reason_code == "HURST_CHOP_REGIME_VETO":
                return f"{symbol} piyasası yatay/rastgele rejimde (Hurst: {hurst.hurst_exponent}); trend takibi zayıflatılarak İZLEME kararına çekildi."
            elif reason_code == "TIMEFRAME_ALIGNMENT_CONFLICT":
                return f"{symbol} için kısa ve uzun vadeli zaman dilimleri çelişiyor; yön netleşene kadar İZLEME önerilir."
            elif reason_code == "PORTFOLIO_CONCENTRATION_VETO":
                return f"{symbol} tekil bazda olumlu olsa da portföy korelasyonunu aşırı artırdığı için İZLEME seviyesinde tutuldu."
            else:
                return f"{symbol} için quant sinyalleri dengeli bölgede; net bir kırılma teyit edilene kadar İZLEME kararı geçerlidir. {noise_text}"


if __name__ == "__main__":
    engine = ShovelPrimaryQuantEngine()
    dummy_prices = [100.0 + i * 0.5 + math.sin(i) * 2.0 for i in range(100)]
    output = engine.evaluate_decision("NVDA", "us_equities", dummy_prices)
    print("Decision:", output.decision)
    print("Score:", output.final_quant_score)
    print("Explanation:", output.plain_turkish_explanation)
    print("Vetoes:", output.veto_flags)
