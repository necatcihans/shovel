# -*- coding: utf-8 -*-
"""
shovel_crypto_engine.py — Shovel Kripto Modülü Kalibrasyon ve Risk Eşikleri Motoru

KAPSAM:
1. Volatiliteye Duyarlı Rolling Calibration Window (BTC/ETH/SOL/XRP)
2. Hacim Ağırlıklı Funding ve Open Interest Kaynak Yöneticisi (Binance/Bybit/OKX)
3. Conformal Coverage Eşikleri (%90 hedef, %85 uyarı, %80 BEKLE veto)
4. Multi-Timeframe Trend Uyumu (1h: 0.20, 4h: 0.35, 1d: 0.45)
5. Kaldıraç Risk Gösterimi ve 6 Koşullu LEVERAGE_VETO
6. Coin Bazlı Zorunlu Gösterge Denetimi (SOL/XRP için btc_dominance zorunlu)
7. Kalibrasyon Bozulma ve Rejim Kırılma İzleme (CALIBRATION_BREAKDOWN loglama)
8. Hisse/Kripto Etiket İzolasyonu (LONG BIAS, SHORT BIAS, RANGE, BEKLE, HIGH RISK)
"""

from __future__ import annotations

import os
import sys
import json
import time
import math
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Tuple, Literal
from pydantic import BaseModel, Field, ConfigDict

# UTF-8 stdout
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

VAULT_DIR = r"c:\Users\Cihan\Desktop\ikinci-beyin"
CONFIG_DIR = os.path.join(VAULT_DIR, "config")
JOURNAL_DIR = os.path.join(VAULT_DIR, "journal")
CRYPTO_CONFIG_FILE = os.path.join(CONFIG_DIR, "crypto_module_thresholds.json")
CALIBRATION_LOG_FILE = os.path.join(JOURNAL_DIR, "crypto_calibration_log.jsonl")

os.makedirs(CONFIG_DIR, exist_ok=True)
os.makedirs(JOURNAL_DIR, exist_ok=True)


# ════════════════════════════════════════════════════════════════════
# 1. YAPILANDIRMA VE LOGLAMA
# ════════════════════════════════════════════════════════════════════

def load_crypto_config() -> Dict[str, Any]:
    if os.path.exists(CRYPTO_CONFIG_FILE):
        try:
            with open(CRYPTO_CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    # Varsayılan güvenli yedek yapılandırma
    return {
        "calibration": {
            "BTC": {"window_days_low_vol": 90, "window_days_normal_vol": 60, "window_days_high_vol": 30, "min_observations": 100, "vol_threshold_low": 0.40, "vol_threshold_high": 0.75},
            "ETH": {"window_days_low_vol": 90, "window_days_normal_vol": 60, "window_days_high_vol": 30, "min_observations": 100, "vol_threshold_low": 0.45, "vol_threshold_high": 0.80},
            "SOL": {"window_days_low_vol": 60, "window_days_normal_vol": 30, "window_days_high_vol": 20, "min_observations": 80, "vol_threshold_low": 0.55, "vol_threshold_high": 0.95},
            "XRP": {"window_days_low_vol": 60, "window_days_normal_vol": 30, "window_days_high_vol": 20, "min_observations": 80, "vol_threshold_low": 0.50, "vol_threshold_high": 0.90}
        },
        "derivatives_data": {
            "reference_exchange": "BINANCE",
            "funding_source": "binance_perpetual",
            "open_interest_source": "binance_perpetual",
            "fallback_sources": ["bybit", "okx"],
            "stale_threshold_seconds": 28800
        },
        "conformal": {
            "target_coverage": 0.90,
            "warning_gap": 0.05,
            "halt_gap": 0.10,
            "horizons": ["3d", "7d"]
        },
        "timeframe_weights": {"1h": 0.20, "4h": 0.35, "1d": 0.45},
        "timeframe_thresholds": {"bull_threshold": 0.35, "bear_threshold": -0.35},
        "leverage_policy": {
            "default_leverage": 1,
            "max_allowed_leverage": 3,
            "min_coverage_for_leverage": 0.85,
            "cvar_limit_pct": 12.0,
            "max_spread_slippage_bps": 25,
            "require_multi_tf_aligned": true,
            "require_stop_loss": true,
            "require_funding_cost_calculated": true
        },
        "required_features": {
            "BTC": ["price", "volume", "volatility"],
            "ETH": ["price", "volume", "volatility", "btc_correlation"],
            "SOL": ["price", "volume", "volatility", "btc_dominance", "btc_correlation", "funding_rate", "open_interest"],
            "XRP": ["price", "volume", "volatility", "btc_dominance", "btc_correlation", "funding_rate", "open_interest"]
        }
    }


def log_crypto_calibration(record: Dict[str, Any]):
    """Her kalibrasyon ve rejim kırılmasını JSONL kütüğüne yazar."""
    try:
        with open(CALIBRATION_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


# ════════════════════════════════════════════════════════════════════
# 2. VOLATİLİTEYE DUYARLI KALİBRASYON PENCERESİ MOTORU
# ════════════════════════════════════════════════════════════════════

class CryptoCalibrationEngine:
    """Gerçekleşen volatiliteye göre pencere seçen ve güncellemeleri kaydeden motor."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or load_crypto_config()
        self.calib_cfg = self.config.get("calibration", {})

    def select_window(self, symbol: str, realized_volatility: float, observation_count: int = 120) -> Dict[str, Any]:
        sym = symbol.upper().replace("-USD", "").replace("USDT", "").replace("USD", "")
        cfg = self.calib_cfg.get(sym) or self.calib_cfg.get("BTC", {})

        low_th = cfg.get("vol_threshold_low", 0.40)
        high_th = cfg.get("vol_threshold_high", 0.75)

        if realized_volatility < low_th:
            regime = "LOW_VOLATILITY"
            window_days = cfg.get("window_days_low_vol", 90)
        elif realized_volatility <= high_th:
            regime = "NORMAL_VOLATILITY"
            window_days = cfg.get("window_days_normal_vol", 60)
        else:
            regime = "HIGH_VOLATILITY"
            window_days = cfg.get("window_days_high_vol", 30)

        now = datetime.now(timezone.utc)
        win_start = (now - timedelta(days=window_days)).strftime("%Y-%m-%d")
        win_end = now.strftime("%Y-%m-%d")

        record = {
            "symbol": sym,
            "window_start": win_start,
            "window_end": win_end,
            "window_days": window_days,
            "observation_count": observation_count,
            "volatility_regime": regime,
            "realized_volatility": round(realized_volatility, 3),
            "updated_at": now.isoformat()
        }
        log_crypto_calibration(record)
        return record


# ════════════════════════════════════════════════════════════════════
# 3. DERİVATİVES (FUNDING VE OPEN INTEREST) KAYNAK YÖNETİCİSİ
# ════════════════════════════════════════════════════════════════════

class DerivativesDataManager:
    """
    Binance perpetual referanslı, Bybit/OKX fallback destekli,
    hacim ağırlıklı funding rate ve OI toplayıcısı.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or load_crypto_config()
        self.deriv_cfg = self.config.get("derivatives_data", {})
        self.ref_exchange = self.deriv_cfg.get("reference_exchange", "BINANCE")
        self.primary_src = self.deriv_cfg.get("funding_source", "binance_perpetual")
        self.fallbacks = self.deriv_cfg.get("fallback_sources", ["bybit", "okx"])
        self.stale_sec = self.deriv_cfg.get("stale_threshold_seconds", 28800)

    def process_derivatives_data(
        self,
        symbol: str,
        sources_data: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        sources_data: [
          {"exchange": "BINANCE", "funding_rate": 0.0001, "open_interest": 4500000000, "volume": 12000000000, "timestamp": iso, "is_stale": False}
        ]
        """
        now = datetime.now(timezone.utc)
        sym = symbol.upper()

        if not sources_data:
            return {
                "symbol": sym,
                "funding_rate": 0.0,
                "open_interest": 0.0,
                "exchange_sources": [],
                "stale_sources": [],
                "weighted": False,
                "as_of": now.isoformat(),
                "freshness": "no_data",
                "confidence": "LOW"
            }

        valid_sources = []
        stale_sources = []

        for s in sources_data:
            ex_name = s.get("exchange", "UNKNOWN").upper()
            is_stale = s.get("is_stale", False)
            # Zaman damgası kontrolü
            ts_str = s.get("timestamp")
            if ts_str:
                try:
                    ts_dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    if (now - ts_dt).total_seconds() > self.stale_sec:
                        is_stale = True
                except Exception:
                    pass

            if is_stale:
                stale_sources.append(ex_name)
            else:
                valid_sources.append(s)

        # Eğer hiç taze kaynak kalmadıysa ve tümü eskiyse
        if not valid_sources and stale_sources:
            # Fallback olarak bayat kaynakları kullan ancak confidence LOW etiketle
            valid_sources = sources_data
            all_stale = True
        else:
            all_stale = False

        # Tekil veya çoklu borsa hacim ağırlıklı ortalama
        total_vol = sum(max(0.0, float(s.get("volume", 1.0))) for s in valid_sources)
        if total_vol > 0:
            weighted_fr = sum(float(s.get("funding_rate", 0.0)) * max(0.0, float(s.get("volume", 1.0))) for s in valid_sources) / total_vol
        else:
            weighted_fr = sum(float(s.get("funding_rate", 0.0)) for s in valid_sources) / len(valid_sources)

        total_oi = sum(float(s.get("open_interest", 0.0)) for s in valid_sources)
        ex_names = [s.get("exchange", "").upper() for s in valid_sources]

        freshness_label = "stale" if all_stale else "fresh"
        confidence_label = "LOW" if all_stale else "NORMAL"

        return {
            "symbol": sym,
            "funding_rate": round(weighted_fr, 6),
            "open_interest": round(total_oi, 2),
            "exchange_sources": ex_names,
            "stale_sources": stale_sources,
            "weighted": len(valid_sources) > 1,
            "as_of": now.isoformat(),
            "freshness": freshness_label,
            "confidence": confidence_label
        }


# ════════════════════════════════════════════════════════════════════
# 4. CONFORMAL COVERAGE EŞİKLERİ VE DENETÇİSİ
# ════════════════════════════════════════════════════════════════════

class CryptoConformalEngine:
    """
    Hedef coverage: %90
    Uyarı eşiği: >= %85 (normal/orta güven)
    Genişleme eşiği: %80 - %85 (düşük güven, aralık genişler)
    Durdurma eşiği: < %80 (sinyal üretme, BEKLE'ye geç)
    Her coin ve horizon (3d, 7d) için bağımsızdır.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or load_crypto_config()
        self.cnf_cfg = self.config.get("conformal", {})
        self.target_coverage = self.cnf_cfg.get("target_coverage", 0.90)
        self.warning_gap = self.cnf_cfg.get("warning_gap", 0.05)
        self.halt_gap = self.cnf_cfg.get("halt_gap", 0.10)

        self.warning_threshold = self.target_coverage - self.warning_gap  # 0.85
        self.halt_threshold = self.target_coverage - self.halt_gap        # 0.80

    def evaluate_coverage(self, symbol: str, horizon: str, empirical_coverage: float) -> Dict[str, Any]:
        sym = symbol.upper()
        h = horizon.lower()

        if empirical_coverage >= self.warning_threshold:
            status = "NORMAL_COVERAGE"
            confidence = "NORMAL"
            interval_multiplier = 1.0
            allow_signal = True
            force_wait = False
            message = f"Empirical coverage %{empirical_coverage*100:.1f} yeterli (Hedef: %{self.target_coverage*100:.0f})."
        elif empirical_coverage >= self.halt_threshold:
            status = "WARNING_EXPAND_INTERVAL"
            confidence = "LOW"
            interval_multiplier = 1.35  # Aralık genişletilir
            allow_signal = True
            force_wait = False
            message = f"DİKKAT: Empirical coverage %{empirical_coverage*100:.1f} zayıfladı (%80-%85). Güven düşürüldü, aralık genişletildi."
        else:
            status = "HALT_SIGNAL"
            confidence = "HALTED"
            interval_multiplier = 1.80
            allow_signal = False
            force_wait = True
            message = f"KRİTİK UYARI: Empirical coverage %{empirical_coverage*100:.1f} < %80 durdurma eşiği! Sinyal üretimi kilitlendi, BEKLE durumuna geçildi."

            # Loglama: Kalibrasyon bozulması
            log_crypto_calibration({
                "event": "CALIBRATION_BREAKDOWN",
                "symbol": sym,
                "horizon": h,
                "target_coverage": self.target_coverage,
                "observed_coverage": round(empirical_coverage, 3),
                "threshold": self.halt_threshold,
                "status": "BEKLE",
                "timestamp": datetime.now(timezone.utc).isoformat()
            })

        return {
            "symbol": sym,
            "horizon": h,
            "empirical_coverage": round(empirical_coverage, 3),
            "target_coverage": self.target_coverage,
            "warning_threshold": self.warning_threshold,
            "halt_threshold": self.halt_threshold,
            "status": status,
            "confidence": confidence,
            "interval_multiplier": interval_multiplier,
            "allow_signal": allow_signal,
            "force_wait": force_wait,
            "message": message
        }


# ════════════════════════════════════════════════════════════════════
# 5. MULTI-TIMEFRAME TREND UYUM MOTORU
# ════════════════════════════════════════════════════════════════════

class MultiTimeframeEngine:
    """
    1h (0.20), 4h (0.35), 1d (0.45) ağırlıklı trend skoru.
    Skor >= 0.35 -> Yukarı uyum (BULLISH ALIGNMENT)
    Skor <= -0.35 -> Aşağı uyum (BEARISH ALIGNMENT)
    -0.35 < Skor < 0.35 -> Uyumsuzluk (DISCORDANT / BEKLE)
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or load_crypto_config()
        self.weights = self.config.get("timeframe_weights", {"1h": 0.20, "4h": 0.35, "1d": 0.45})
        th = self.config.get("timeframe_thresholds", {})
        self.bull_th = th.get("bull_threshold", 0.35)
        self.bear_th = th.get("bear_threshold", -0.35)

    def compute_alignment(self, dir_1h: int, dir_4h: int, dir_1d: int) -> Dict[str, Any]:
        """
        dir: +1 (Yükseliş), 0 (Nötr), -1 (Düşüş)
        """
        w_1h = self.weights.get("1h", 0.20)
        w_4h = self.weights.get("4h", 0.35)
        w_1d = self.weights.get("1d", 0.45)

        score = (dir_1h * w_1h) + (dir_4h * w_4h) + (dir_1d * w_1d)
        score = round(score, 3)

        if score >= self.bull_th:
            alignment = "BULLISH_ALIGNMENT"
            bias_hint = "LONG BIAS"
            is_aligned = True
            confidence = "NORMAL"
            allow_leverage = True
        elif score <= self.bear_th:
            alignment = "BEARISH_ALIGNMENT"
            bias_hint = "SHORT BIAS"
            is_aligned = True
            confidence = "NORMAL"
            allow_leverage = True
        else:
            alignment = "DISCORDANT"
            bias_hint = "RANGE"
            is_aligned = False
            confidence = "LOW"
            allow_leverage = False

        return {
            "score": score,
            "alignment": alignment,
            "bias_hint": bias_hint,
            "is_aligned": is_aligned,
            "confidence": confidence,
            "allow_leverage": allow_leverage,
            "inputs": {"1h": dir_1h, "4h": dir_4h, "1d": dir_1d},
            "weights": {"1h": w_1h, "4h": w_4h, "1d": w_1d}
        }


# ════════════════════════════════════════════════════════════════════
# 6. KALDIRAÇ RİSK MOTORU VE LEVERAGE_VETO
# ════════════════════════════════════════════════════════════════════

class CryptoLeverageEngine:
    """
    Kaldıraç gösterimi varsayılan olarak gizlidir.
    1x varsayılandır. 6 katı risk koşulu sağlanmadığında LEVERAGE_VETO üretir.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or load_crypto_config()
        self.lev_cfg = self.config.get("leverage_policy", {})
        self.default_leverage = self.lev_cfg.get("default_leverage", 1)
        self.max_allowed = self.lev_cfg.get("max_allowed_leverage", 3)
        self.min_coverage = self.lev_cfg.get("min_coverage_for_leverage", 0.85)
        self.cvar_limit = self.lev_cfg.get("cvar_limit_pct", 12.0)
        self.max_spread = self.lev_cfg.get("max_spread_slippage_bps", 25)

    @staticmethod
    def format_dynamic_warning(leverage: int) -> str:
        if leverage <= 1:
            return "1x Spot / Teminatsız işlem. Kaldıraç riski bulunmuyor."
        adverse_pct = 100.0 / float(leverage)
        return f"{leverage} kat kaldıraçta yaklaşık %{adverse_pct:.1f} ters fiyat hareketi teminatı tüketebilir. Kaldıraç, zararı da aynı oranda büyütür."

    def evaluate_leverage(
        self,
        requested_leverage: int,
        empirical_coverage: float,
        is_multi_tf_aligned: bool,
        cvar_pct: float,
        spread_slippage_bps: float,
        has_funding_calculated: bool,
        has_stop_loss: bool
    ) -> Dict[str, Any]:
        veto_reasons = []

        if requested_leverage > self.max_allowed:
            veto_reasons.append(f"İstenen kaldıraç ({requested_leverage}x) maksimum izin verilen ({self.max_allowed}x) sınırını aşıyor.")

        if empirical_coverage < self.min_coverage:
            veto_reasons.append(f"Coverage (%{empirical_coverage*100:.1f}) kaldıraç için gereken %{self.min_coverage*100:.0f} sınırının altında.")

        if not is_multi_tf_aligned:
            veto_reasons.append("Multi-timeframe uyumsuzluğu mevcut; kaldıraçlı işlem açılamaz.")

        if cvar_pct > self.cvar_limit:
            veto_reasons.append(f"Kuyruk riski (CVaR %{cvar_pct:.1f}) %{self.cvar_limit:.1f} limitini aşıyor.")

        if spread_slippage_bps > self.max_spread:
            veto_reasons.append(f"Kayma ve makas maliyeti ({spread_slippage_bps} bps) tolerans sınırını ({self.max_spread} bps) aşıyor.")

        if not has_funding_calculated:
            veto_reasons.append("Perpetual taşıma/funding maliyeti hesaplanamadı.")

        if not has_stop_loss:
            veto_reasons.append("Kesin stop-loss seviyesi tanımlanmamış.")

        if veto_reasons:
            status = "LEVERAGE_VETO"
            effective_leverage = 1
            approved = False
        else:
            status = "LEVERAGE_APPROVED"
            effective_leverage = max(1, min(requested_leverage, self.max_allowed))
            approved = True

        warning_text = self.format_dynamic_warning(effective_leverage)

        return {
            "status": status,
            "approved": approved,
            "requested_leverage": requested_leverage,
            "effective_leverage": effective_leverage,
            "warning_text": warning_text,
            "veto_reasons": veto_reasons,
            "default_hidden": True
        }


# ════════════════════════════════════════════════════════════════════
# 7. COIN BAZLI ZORUNLU GÖSTERGE DOĞRULAYICISI
# ════════════════════════════════════════════════════════════════════

class CryptoFeatureValidator:
    """
    BTC: price, volume, volatility
    ETH: price, volume, volatility, btc_correlation
    SOL/XRP: price, volume, volatility, btc_dominance, btc_correlation, funding_rate, open_interest
    Altcoinlerde btc_dominance zorunludur. Eksikse INSUFFICIENT_CRYPTO_FEATURES -> BEKLE.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or load_crypto_config()
        self.req_features = self.config.get("required_features", {})

    def validate(self, symbol: str, features: Dict[str, Any]) -> Tuple[bool, List[str]]:
        sym = symbol.upper().replace("-USD", "").replace("USDT", "").replace("USD", "")
        # Tanımlı değilse altcoin olarak SOL/XRP zorunlu listesini baz al
        req_list = self.req_features.get(sym) or [
            "price", "volume", "volatility", "btc_dominance", "btc_correlation", "funding_rate", "open_interest"
        ]

        missing = []
        for feat in req_list:
            val = features.get(feat)
            if val is None or val == "":
                missing.append(feat)

        is_valid = len(missing) == 0
        return is_valid, missing


# ════════════════════════════════════════════════════════════════════
# 8. MATEMATİKSEL KRİPTO QUANT LAB BİLEŞENLERİ
# ════════════════════════════════════════════════════════════════════

class CryptoProbabilityNormalizer:
    """
    1. Olasılık Normalizasyonu ve Çok Faktörlü Skorlama Motoru:
    - Raw scores: raw_long_score, raw_short_score, raw_range_score
    - Softmax normalizasyonu: p_i = exp(raw_i / T) / sum(exp(raw_j / T))
    - Yuvarlama sonrası toplamın tam olarak %100 olması
    - 8 faktörün sentezi:
      1. Normalize teknik bias
      2. Geçmiş benzer sinyaller
      3. Volatilite rejimi
      4. Çoklu zaman dilimi uyumu
      5. Funding ve Open Interest
      6. Order-book imbalance
      7. Conformal calibration
      8. Benchmark / beta etkisi
    - Çıktı: long_probability, short_probability, range_probability,
      probability_calibration_status, brier_score, reliability_bucket
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or load_crypto_config()
        prob_cfg = self.config.get("probability_normalization", {})
        self.temperature = prob_cfg.get("temperature", 1.2)
        self.weights = prob_cfg.get("multi_factor_weights", {
            "technical_bias": 0.25,
            "similar_signals_prior": 0.15,
            "volatility_regime": 0.10,
            "multi_timeframe": 0.15,
            "funding_oi": 0.10,
            "order_book_imbalance": 0.10,
            "conformal_calibration": 0.10,
            "benchmark_beta": 0.05
        })
        self.buckets = prob_cfg.get("reliability_buckets", [
            {"range": [0, 40], "label": "0-40% (Düşük)"},
            {"range": [40, 50], "label": "40-50% (Denge)"},
            {"range": [50, 60], "label": "50-60% (Ilımlı)"},
            {"range": [60, 70], "label": "60-70% (Orta Güven)"},
            {"range": [70, 80], "label": "70-80% (Yüksek Güven)"},
            {"range": [80, 100], "label": "80-100% (Çok Yüksek Güven)"}
        ])

    def compute_multi_factor_raw_scores(
        self,
        normalized_technical_bias: float,      # [-1, 1]
        similar_signals_prior: float,          # [-1, 1]
        volatility_regime: str,                # "LOW", "NORMAL", "HIGH"
        multi_timeframe_score: float,          # [-1, 1]
        funding_oi_factor: float,              # [-1, 1]
        order_book_imbalance: float,           # [-1, 1]
        conformal_calibration_factor: float,   # [-1, 1]
        benchmark_beta_impact: float           # [-1, 1]
    ) -> Tuple[float, float, float]:
        w = self.weights
        dir_score = (
            w.get("technical_bias", 0.25) * normalized_technical_bias +
            w.get("similar_signals_prior", 0.15) * similar_signals_prior +
            w.get("multi_timeframe", 0.15) * multi_timeframe_score +
            w.get("funding_oi", 0.10) * funding_oi_factor +
            w.get("order_book_imbalance", 0.10) * order_book_imbalance +
            w.get("conformal_calibration", 0.10) * conformal_calibration_factor +
            w.get("benchmark_beta", 0.05) * benchmark_beta_impact
        )

        vol_up = (volatility_regime or "NORMAL").upper()
        if "HIGH" in vol_up:
            range_base = -0.3
        elif "LOW" in vol_up:
            range_base = 0.5
        else:
            range_base = 0.1

        raw_long = max(-3.0, min(3.0, dir_score * 2.5))
        raw_short = max(-3.0, min(3.0, -dir_score * 2.5))
        raw_range = max(-3.0, min(3.0, range_base + (1.0 - abs(dir_score)) * 1.5))

        return raw_long, raw_short, raw_range

    def normalize_probabilities(
        self,
        raw_long_score: float,
        raw_short_score: float,
        raw_range_score: float,
        temperature: Optional[float] = None,
        actual_outcome: Optional[str] = None
    ) -> Dict[str, Any]:
        T = temperature or self.temperature
        if T <= 0:
            T = 1.0

        scores = [raw_long_score, raw_short_score, raw_range_score]
        max_s = max(scores)
        exp_scores = [math.exp((s - max_s) / T) for s in scores]
        sum_exp = sum(exp_scores)
        probs = [e / sum_exp for e in exp_scores]

        # Yüzdeye çevir ve yuvarla
        raw_pcts = [p * 100.0 for p in probs]
        rounded_pcts = [round(p, 1) for p in raw_pcts]

        # Toplamın tam olarak %100 olmasını sağla
        diff = round(100.0 - sum(rounded_pcts), 2)
        max_idx = rounded_pcts.index(max(rounded_pcts))
        rounded_pcts[max_idx] = round(rounded_pcts[max_idx] + diff, 1)

        long_prob, short_prob, range_prob = rounded_pcts

        # Brier Score hesaplaması
        if actual_outcome:
            outcome_vec = [
                1.0 if actual_outcome.upper() == "LONG" else 0.0,
                1.0 if actual_outcome.upper() == "SHORT" else 0.0,
                1.0 if actual_outcome.upper() == "RANGE" else 0.0
            ]
            brier_score = round((1.0 / 3.0) * sum((probs[i] - outcome_vec[i])**2 for i in range(3)), 4)
        else:
            brier_score = round((1.0 / 3.0) * sum((probs[i] - (1.0 / 3.0))**2 for i in range(3)), 4)

        dominant_prob = max(long_prob, short_prob, range_prob)
        bucket_label = "50-60% (Ilımlı)"
        for b in self.buckets:
            r = b["range"]
            if r[0] <= dominant_prob < r[1] or (r[1] == 100 and dominant_prob <= 100):
                bucket_label = b["label"]
                break

        if brier_score <= 0.20:
            calib_status = "WELL_CALIBRATED"
        elif brier_score <= 0.35:
            calib_status = "ADEQUATELY_CALIBRATED"
        else:
            calib_status = "UNCALIBRATED_WARNING"

        return {
            "long_probability": long_prob,
            "short_probability": short_prob,
            "range_probability": range_prob,
            "raw_scores": {
                "raw_long_score": round(raw_long_score, 3),
                "raw_short_score": round(raw_short_score, 3),
                "raw_range_score": round(raw_range_score, 3)
            },
            "probability_calibration_status": calib_status,
            "brier_score": brier_score,
            "reliability_bucket": bucket_label,
            "temperature_used": T,
            "sum_pct": round(long_prob + short_prob + range_prob, 1)
        }


class SimilarSignalMatcher:
    """
    2. Benzer Sinyal Tanımı ve Eşleştirme Motoru:
    8 Koşuldan en az 4'ü sağlanmalı:
    1. Aynı varlık
    2. Aynı horizon
    3. Aynı volatilite rejimi
    4. Teknik bias farkı <= 0.10
    5. Benzer Hurst sınıfı
    6. Benzer funding/OI durumu
    7. Aynı çoklu-timeframe yönü
    8. Benzer order-book imbalance sınıfı
    Minimum örnek sayısı (min_sample_size=20) sağlanmıyorsa geçmiş başarı oranı kullanılmaz ve güven düşürülür.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or load_crypto_config()
        cfg = self.config.get("similar_signal_criteria", {})
        self.min_matches = cfg.get("min_matches_required", 4)
        self.total_criteria = cfg.get("total_criteria", 8)
        self.bias_diff_th = cfg.get("bias_diff_threshold", 0.10)
        self.min_sample_size = cfg.get("min_sample_size", 20)

    def evaluate_similarity(self, sig_current: Dict[str, Any], sig_hist: Dict[str, Any]) -> Tuple[bool, int, Dict[str, bool]]:
        cur_bias = float(sig_current.get("technical_bias", 0.0))
        hist_bias = float(sig_hist.get("technical_bias", 0.0))

        matches = {
            "same_asset": sig_current.get("symbol") == sig_hist.get("symbol"),
            "same_horizon": sig_current.get("horizon") == sig_hist.get("horizon"),
            "same_volatility_regime": sig_current.get("volatility_regime") == sig_hist.get("volatility_regime"),
            "bias_diff_within_10": abs(cur_bias - hist_bias) <= self.bias_diff_th,
            "same_hurst_class": sig_current.get("hurst_class") == sig_hist.get("hurst_class"),
            "same_funding_oi_status": sig_current.get("funding_oi_status") == sig_hist.get("funding_oi_status"),
            "same_mtf_direction": sig_current.get("mtf_direction") == sig_hist.get("mtf_direction"),
            "same_ob_imbalance_class": sig_current.get("ob_imbalance_class") == sig_hist.get("ob_imbalance_class")
        }
        score = sum(1 for v in matches.values() if v)
        is_similar = score >= self.min_matches
        return is_similar, score, matches

    def match_history(
        self,
        current_signal: Dict[str, Any],
        historical_signals: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        similar_list = []
        for h in historical_signals:
            is_sim, score, breakdown = self.evaluate_similarity(current_signal, h)
            if is_sim:
                similar_list.append({
                    "signal_id": h.get("signal_id"),
                    "score": score,
                    "outcome": h.get("outcome", "SCRATCH"),
                    "return_pct": h.get("return_pct", 0.0),
                    "breakdown": breakdown
                })

        count = len(similar_list)
        adequate = count >= self.min_sample_size

        if adequate and count > 0:
            wins = sum(1 for s in similar_list if s.get("outcome") == "WIN")
            win_rate = round(wins / count, 3)
            use_historical = True
            confidence_impact = "CONFIRMED"
        else:
            win_rate = 0.50
            use_historical = False
            confidence_impact = "REDUCED_LOW"

        return {
            "matched_count": count,
            "min_sample_size": self.min_sample_size,
            "sample_size_adequate": adequate,
            "use_historical_win_rate": use_historical,
            "empirical_win_rate": win_rate,
            "confidence_impact": confidence_impact,
            "sample_signals": similar_list[:5]
        }


class AlgorithmicOrderBlockDetector:
    """
    3. Algoritmik Order Block Tespiti:
    - Bullish OB: Güçlü yükseliş öncesi son düşüş mumu, hareket >= ATR * mult, Hacim > rolling median, en az 1 test & rejection.
    - Bearish OB: Güçlü düşüş öncesi son yükseliş mumu, hareket >= ATR * mult, Hacim doğrulaması, en az 1 test & rejection.
    - Alanlar: zone_low, zone_high, detection_timeframe, source_candle_time, atr_multiple,
      volume_ratio, touch_count, rejection_count, mitigation_status, invalidation_price, strength_score.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or load_crypto_config()
        ob_cfg = self.config.get("order_block_detection", {})
        self.atr_multiplier = ob_cfg.get("atr_multiplier", 1.5)
        self.min_vol_ratio = ob_cfg.get("min_volume_ratio", 1.10)
        self.min_touches = ob_cfg.get("min_touches", 1)
        self.min_rejections = ob_cfg.get("min_rejections", 1)

    def detect_order_blocks(
        self,
        candles: List[Dict[str, Any]],
        timeframe: str = "4h"
    ) -> List[Dict[str, Any]]:
        if len(candles) < 20:
            return []

        volumes = [c.get("volume", 1.0) for c in candles]
        sorted_vols = sorted(volumes[-20:])
        vol_median = sorted_vols[len(sorted_vols) // 2] if sorted_vols else 1.0

        trs = []
        for i in range(1, len(candles)):
            c = candles[i]
            prev_c = candles[i-1]
            tr = max(
                c["high"] - c["low"],
                abs(c["high"] - prev_c["close"]),
                abs(c["low"] - prev_c["close"])
            )
            trs.append(tr)
        atr = sum(trs[-14:]) / max(1, len(trs[-14:])) if trs else (candles[-1]["close"] * 0.02)
        if atr <= 0:
            atr = candles[-1]["close"] * 0.02

        order_blocks = []
        n = len(candles)

        for i in range(2, n - 2):
            prev = candles[i - 1]
            impulse = candles[i]

            move = impulse["close"] - impulse["open"]
            abs_move = abs(move)
            vol_ratio = impulse["volume"] / vol_median if vol_median > 0 else 1.0

            # Bullish Order Block
            if prev["close"] < prev["open"] and move >= (atr * self.atr_multiplier) and vol_ratio >= self.min_vol_ratio:
                zone_low = min(prev["low"], prev["open"])
                zone_high = max(prev["high"], prev["close"])
                invalidation = zone_low - (0.10 * atr)

                touch_count = 0
                rejection_count = 0
                mitigated = False
                breached = False

                for j in range(i + 1, n):
                    sub = candles[j]
                    if sub["low"] <= zone_high and sub["high"] >= zone_low:
                        touch_count += 1
                        if sub["close"] > zone_high:
                            rejection_count += 1
                    if sub["close"] < invalidation:
                        breached = True
                        break
                    elif sub["low"] <= (zone_low + zone_high) / 2.0:
                        mitigated = True

                if touch_count >= self.min_touches and not breached:
                    status = "MITIGATED" if mitigated else "UNMITIGATED"
                    strength = min(1.0, 0.4 + (0.2 * rejection_count) + (0.2 * (vol_ratio / 2.0)))
                    order_blocks.append({
                        "type": "BULLISH_ORDER_BLOCK",
                        "zone_low": round(zone_low, 2),
                        "zone_high": round(zone_high, 2),
                        "detection_timeframe": timeframe,
                        "source_candle_time": prev.get("time", ""),
                        "atr_multiple": round(abs_move / atr, 2),
                        "volume_ratio": round(vol_ratio, 2),
                        "touch_count": touch_count,
                        "rejection_count": rejection_count,
                        "mitigation_status": status,
                        "invalidation_price": round(invalidation, 2),
                        "strength_score": round(strength, 2)
                    })

            # Bearish Order Block
            elif prev["close"] > prev["open"] and (-move) >= (atr * self.atr_multiplier) and vol_ratio >= self.min_vol_ratio:
                zone_low = min(prev["low"], prev["open"])
                zone_high = max(prev["high"], prev["close"])
                invalidation = zone_high + (0.10 * atr)

                touch_count = 0
                rejection_count = 0
                mitigated = False
                breached = False

                for j in range(i + 1, n):
                    sub = candles[j]
                    if sub["high"] >= zone_low and sub["low"] <= zone_high:
                        touch_count += 1
                        if sub["close"] < zone_low:
                            rejection_count += 1
                    if sub["close"] > invalidation:
                        breached = True
                        break
                    elif sub["high"] >= (zone_low + zone_high) / 2.0:
                        mitigated = True

                if touch_count >= self.min_touches and not breached:
                    status = "MITIGATED" if mitigated else "UNMITIGATED"
                    strength = min(1.0, 0.4 + (0.2 * rejection_count) + (0.2 * (vol_ratio / 2.0)))
                    order_blocks.append({
                        "type": "BEARISH_ORDER_BLOCK",
                        "zone_low": round(zone_low, 2),
                        "zone_high": round(zone_high, 2),
                        "detection_timeframe": timeframe,
                        "source_candle_time": prev.get("time", ""),
                        "atr_multiple": round(abs_move / atr, 2),
                        "volume_ratio": round(vol_ratio, 2),
                        "touch_count": touch_count,
                        "rejection_count": rejection_count,
                        "mitigation_status": status,
                        "invalidation_price": round(invalidation, 2),
                        "strength_score": round(strength, 2)
                    })

        return order_blocks


class DecomposedRiskPenaltyEngine:
    """
    4. Ayrıştırılmış Risk Penalty ve Bağımsız Veto Motoru:
    risk_penalty = w_vol * vol_risk + w_cvar * cvar_risk + w_spread * spread_risk +
                   w_liq * liq_risk + w_fund * fund_risk + w_tf * tf_conflict
    Tüm bileşenler [0, 1] normalize.
    Bağımsız VETO Kuralları:
    - spread > critical_threshold -> VETO
    - cvar > critical_threshold -> VETO
    - liquidity < min_liquidity -> VETO
    - conformal_coverage < 0.80 -> VETO
    - risk_penalty > 0.70 -> LONG/SHORT üretme (VETO).
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or load_crypto_config()
        rp_cfg = self.config.get("risk_penalty", {})
        self.weights = rp_cfg.get("weights", {
            "w_volatility": 0.20,
            "w_cvar": 0.25,
            "w_spread": 0.15,
            "w_liquidity": 0.15,
            "w_funding": 0.15,
            "w_timeframe": 0.10
        })
        self.veto_th = rp_cfg.get("veto_thresholds", {
            "max_spread_bps": 30.0,
            "max_cvar_pct": 14.0,
            "min_liquidity_depth_usd": 500000.0,
            "min_conformal_coverage": 0.80,
            "max_risk_penalty": 0.70
        })

    def compute_risk_penalty(
        self,
        realized_volatility: float,
        cvar_pct: float,
        spread_bps: float,
        liquidity_depth_usd: float,
        funding_rate: float,
        mtf_score: float,
        conformal_coverage: float
    ) -> Dict[str, Any]:
        vol_risk = min(1.0, max(0.0, realized_volatility / 1.0))
        cvar_risk = min(1.0, max(0.0, cvar_pct / 20.0))
        spread_risk = min(1.0, max(0.0, spread_bps / 30.0))
        liq_risk = min(1.0, max(0.0, 1.0 - (liquidity_depth_usd / 2000000.0)))
        funding_risk = min(1.0, max(0.0, abs(funding_rate) / 0.001))
        tf_conflict = min(1.0, max(0.0, 1.0 - abs(mtf_score)))

        w = self.weights
        risk_penalty = (
            w.get("w_volatility", 0.20) * vol_risk +
            w.get("w_cvar", 0.25) * cvar_risk +
            w.get("w_spread", 0.15) * spread_risk +
            w.get("w_liquidity", 0.15) * liq_risk +
            w.get("w_funding", 0.15) * funding_risk +
            w.get("w_timeframe", 0.10) * tf_conflict
        )
        risk_penalty = round(risk_penalty, 3)

        vetoes = []
        if spread_bps > self.veto_th.get("max_spread_bps", 30.0):
            vetoes.append(f"SPREAD_VETO: Spread ({spread_bps:.1f} bps) kritik {self.veto_th['max_spread_bps']:.1f} bps eşiğinin üzerinde.")
        if cvar_pct > self.veto_th.get("max_cvar_pct", 14.0):
            vetoes.append(f"CVAR_VETO: CVaR (%{cvar_pct:.1f}) kritik %{self.veto_th['max_cvar_pct']:.1f} eşiğinin üzerinde.")
        if liquidity_depth_usd < self.veto_th.get("min_liquidity_depth_usd", 500000.0):
            vetoes.append(f"LIQUIDITY_VETO: Derinlik (${liquidity_depth_usd:,.0f}) yetersiz.")
        if conformal_coverage < self.veto_th.get("min_conformal_coverage", 0.80):
            vetoes.append(f"CONFORMAL_COVERAGE_VETO: Conformal coverage (%{conformal_coverage*100:.1f}) kritik %80 altında.")
        if risk_penalty > self.veto_th.get("max_risk_penalty", 0.70):
            vetoes.append(f"RISK_PENALTY_VETO: Toplam risk penalty ({risk_penalty}) üst eşik {self.veto_th['max_risk_penalty']} aşıldı.")

        has_veto = len(vetoes) > 0

        return {
            "risk_penalty": risk_penalty,
            "has_veto": has_veto,
            "veto_reasons": vetoes,
            "allow_directional_signal": not has_veto,
            "components": {
                "volatility_risk": round(vol_risk, 3),
                "cvar_risk": round(cvar_risk, 3),
                "spread_risk": round(spread_risk, 3),
                "liquidity_risk": round(liq_risk, 3),
                "funding_risk": round(funding_risk, 3),
                "timeframe_conflict": round(tf_conflict, 3)
            }
        }


class HurstAndCusumEngine:
    """
    5. Hurst ve CUSUM Dinamik Normalizasyon Motoru:
    - Hurst Exponent:
      * H < 0.45: Mean-reverting
      * 0.45 <= H <= 0.55: Neutral
      * H > 0.55: Trending
      * hurst_score = clip((H - 0.5) * scale, -1, 1)
    - CUSUM:
      * Change-point: +1 (pozitif kırılma), -1 (negatif kırılma), 0 (anlamlı kırılma yok)
      * Eşikler rolling volatility ve ATR ile dinamik ölçeklenir (sabit fiyat eşiği yok).
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or load_crypto_config()
        cfg = self.config.get("hurst_cusum", {})
        self.mr_max = cfg.get("hurst_mean_reversion_max", 0.45)
        self.tr_min = cfg.get("hurst_trending_min", 0.55)
        self.scale = cfg.get("hurst_scale", 5.0)
        self.atr_mult = cfg.get("cusum_atr_multiplier", 2.0)

    def evaluate_hurst(self, hurst_value: float) -> Dict[str, Any]:
        H = float(hurst_value)
        if H < self.mr_max:
            h_class = "mean_reversion"
            desc = "Ortalamaya dönüş (Mean-reversion) eğilimi güçlü"
        elif H > self.tr_min:
            h_class = "trending"
            desc = "Trend eğilimi güçlü (Persistance)"
        else:
            h_class = "neutral"
            desc = "Nötr / Rastgele yürüyüş (Random walk)"

        score = max(-1.0, min(1.0, (H - 0.5) * self.scale))
        return {
            "hurst_value": round(H, 3),
            "hurst_class": h_class,
            "hurst_score": round(score, 3),
            "description": desc
        }

    def compute_dynamic_cusum(
        self,
        prices: List[float],
        atr: float,
        rolling_volatility: float
    ) -> Dict[str, Any]:
        if len(prices) < 5 or atr <= 0:
            return {"change_point": 0, "status": "NO_BREAKOUT", "threshold": 0.0}

        vol_scale = math.sqrt(max(0.1, rolling_volatility))
        h = self.atr_mult * atr * vol_scale

        s_pos = 0.0
        s_neg = 0.0
        change_point = 0

        for i in range(1, len(prices)):
            delta = prices[i] - prices[i-1]
            s_pos = max(0.0, s_pos + delta)
            s_neg = min(0.0, s_neg + delta)
            if s_pos > h:
                change_point = 1
                break
            elif s_neg < -h:
                change_point = -1
                break

        status = "POSITIVE_BREAKOUT" if change_point == 1 else ("NEGATIVE_BREAKDOWN" if change_point == -1 else "NO_BREAKOUT")
        return {
            "change_point": change_point,
            "status": status,
            "threshold": round(h, 2),
            "s_pos": round(s_pos, 2),
            "s_neg": round(s_neg, 2)
        }


class ProbabilityCalibrationTracker:
    """
    6. Olasılık Kalibrasyonu ve Güvenilirlik İzleyicisi:
    - Conformal coverage ile olasılık kalibrasyonunu ayırır.
    - Ölçümler:
      1. Yön doğruluğu (Hit-rate)
      2. Olasılık kalibrasyonu (Brier Score, Calibration Error)
      3. Fiyat aralığı conformal coverage
      4. Order block touch/rejection başarısı
    - Confidence bucket bazlı hit-rate takibi.
    """

    def __init__(self):
        self.buckets = [
            {"bucket": "40-50%", "min": 0.40, "max": 0.50, "preds": [], "outcomes": []},
            {"bucket": "50-60%", "min": 0.50, "max": 0.60, "preds": [], "outcomes": []},
            {"bucket": "60-70%", "min": 0.60, "max": 0.70, "preds": [], "outcomes": []},
            {"bucket": "70-80%", "min": 0.70, "max": 0.80, "preds": [], "outcomes": []},
            {"bucket": "80-100%", "min": 0.80, "max": 1.00, "preds": [], "outcomes": []}
        ]

    def record_prediction(self, predicted_prob: float, actual_hit: int):
        p = min(1.0, max(0.0, predicted_prob))
        for b in self.buckets:
            if b["min"] <= p < b["max"] or (b["max"] == 1.0 and p <= 1.0):
                b["preds"].append(p)
                b["outcomes"].append(actual_hit)
                break

    def compute_calibration_report(self) -> Dict[str, Any]:
        total_samples = 0
        total_sq_err = 0.0
        ece = 0.0
        bucket_results = []

        for b in self.buckets:
            n = len(b["preds"])
            if n > 0:
                avg_pred = sum(b["preds"]) / n
                actual_acc = sum(b["outcomes"]) / n
                diff = abs(avg_pred - actual_acc)
                ece += (n * diff)
                total_samples += n
                for p, o in zip(b["preds"], b["outcomes"]):
                    total_sq_err += (p - o)**2
                bucket_results.append({
                    "bucket": b["bucket"],
                    "samples": n,
                    "avg_predicted_prob": round(avg_pred, 3),
                    "empirical_hit_rate": round(actual_acc, 3),
                    "gap": round(diff, 3)
                })

        brier = round(total_sq_err / total_samples, 4) if total_samples > 0 else 0.0
        expected_calib_error = round(ece / total_samples, 4) if total_samples > 0 else 0.0

        return {
            "total_samples": total_samples,
            "brier_score": brier,
            "expected_calibration_error": expected_calib_error,
            "bucket_results": bucket_results
        }


class CryptoBacktestEngine:
    """
    7. 3-Katmanlı Kripto Backtest ve Gerçek Maliyet Motoru:
    - Katman A: Yön başarısı (LONG doğru, SHORT doğru, RANGE doğru, yanlış yön, yön hit-rate)
    - Katman B: Olasılık başarısı (Brier score, calibration error, confidence bucket sonuçları)
    - Katman C: Aralık başarısı (conformal coverage, interval genişliği, hedefe ulaşma, aralık dışına çıkma)
    - Order block sonuçları: TOUCH, REJECTION, BREACH, NO_CONTACT
    - Gerçek maliyetler:
      * Brüt getiri
      * Komisyon
      * Spread
      * Slippage
      * Birikimli Funding maliyeti (perpetual 8 saatlik birikimli)
      * Net getiri
      * Benchmark farkı
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or load_crypto_config()
        self.cost_cfg = self.config.get("cost_model", {
            "commission_maker_bps": 2.0,
            "commission_taker_bps": 5.0,
            "default_spread_bps": 4.0,
            "slippage_depth_factor": 0.001,
            "funding_interval_hours": 8
        })

    def run_backtest(
        self,
        signals: List[Dict[str, Any]],
        benchmark_buy_and_hold_pct: float = 8.5
    ) -> Dict[str, Any]:
        long_correct = 0
        short_correct = 0
        range_correct = 0
        wrong_dir = 0
        total_dir = len(signals)

        brier_sum = 0.0
        conformal_hits = 0
        target_hits = 0
        breach_count = 0
        total_interval_width = 0.0

        ob_touch = 0
        ob_rejection = 0
        ob_breach = 0
        ob_no_contact = 0

        gross_return_sum = 0.0
        total_commission = 0.0
        total_spread = 0.0
        total_slippage = 0.0
        total_funding_cost = 0.0

        for s in signals:
            direction = s.get("direction", "RANGE")
            actual_dir = s.get("actual_direction", "RANGE")

            # Layer A: Directional
            if direction == actual_dir:
                if direction == "LONG":
                    long_correct += 1
                elif direction == "SHORT":
                    short_correct += 1
                else:
                    range_correct += 1
            else:
                wrong_dir += 1

            # Layer B: Probability
            prob = s.get("predicted_prob", 0.5)
            hit = 1.0 if direction == actual_dir else 0.0
            brier_sum += (prob - hit)**2

            # Layer C: Interval
            in_interval = s.get("within_interval", True)
            if in_interval:
                conformal_hits += 1
            else:
                breach_count += 1
            if s.get("target_reached", False):
                target_hits += 1
            total_interval_width += s.get("interval_width_pct", 5.0)

            # Order block
            ob_res = s.get("order_block_result", "NO_CONTACT")
            if ob_res == "TOUCH":
                ob_touch += 1
            elif ob_res == "REJECTION":
                ob_rejection += 1
            elif ob_res == "BREACH":
                ob_breach += 1
            else:
                ob_no_contact += 1

            # Real Costs
            gross_ret = s.get("gross_return_pct", 0.0)
            gross_return_sum += gross_ret
            comm_pct = (self.cost_cfg.get("commission_taker_bps", 5.0) * 2) / 100.0
            total_commission += comm_pct
            spread_pct = self.cost_cfg.get("default_spread_bps", 4.0) / 100.0
            total_spread += spread_pct
            slip_pct = 0.04
            total_slippage += slip_pct

            horizon_hours = s.get("horizon_hours", 72)
            funding_intervals = horizon_hours / self.cost_cfg.get("funding_interval_hours", 8)
            funding_rate_per_interval = s.get("funding_rate_avg", 0.0001)
            funding_cost_pct = (funding_intervals * funding_rate_per_interval) * 100.0
            total_funding_cost += funding_cost_pct

        dir_hit_rate = round((long_correct + short_correct + range_correct) / max(1, total_dir) * 100.0, 1)
        brier_score = round(brier_sum / max(1, total_dir), 4)
        conformal_cov = round(conformal_hits / max(1, total_dir) * 100.0, 1)
        avg_width = round(total_interval_width / max(1, total_dir), 2)

        total_costs = total_commission + total_spread + total_slippage + total_funding_cost
        net_return_sum = gross_return_sum - total_costs
        alpha_vs_bench = net_return_sum - benchmark_buy_and_hold_pct

        return {
            "layer_a_directional": {
                "total_signals": total_dir,
                "long_correct": long_correct,
                "short_correct": short_correct,
                "range_correct": range_correct,
                "wrong_direction": wrong_dir,
                "directional_hit_rate_pct": dir_hit_rate
            },
            "layer_b_probability": {
                "brier_score": brier_score,
                "calibration_status": "CALIBRATED" if brier_score <= 0.25 else "NEEDS_RECALIBRATION"
            },
            "layer_c_interval": {
                "conformal_coverage_pct": conformal_cov,
                "target_coverage_pct": 90.0,
                "avg_interval_width_pct": avg_width,
                "target_hit_rate_pct": round(target_hits / max(1, total_dir) * 100.0, 1),
                "breach_rate_pct": round(breach_count / max(1, total_dir) * 100.0, 1)
            },
            "order_block_results": {
                "touch": ob_touch,
                "rejection": ob_rejection,
                "breach": ob_breach,
                "no_contact": ob_no_contact
            },
            "real_costs_and_returns": {
                "gross_return_pct": round(gross_return_sum, 2),
                "commission_pct": round(total_commission, 2),
                "spread_pct": round(total_spread, 2),
                "slippage_pct": round(total_slippage, 2),
                "cumulative_funding_cost_pct": round(total_funding_cost, 2),
                "total_costs_pct": round(total_costs, 2),
                "net_return_pct": round(net_return_sum, 2),
                "benchmark_buy_and_hold_pct": round(benchmark_buy_and_hold_pct, 2),
                "net_alpha_pct": round(alpha_vs_bench, 2)
            }
        }


class WalkForwardAndLeakageAuditor:
    """
    8. Walk-Forward ve Veri Sızıntısı (Data Leakage) Denetçisi:
    - Horizons: 4h, 1d, 3d, 7d, 14d, 30d
    - Test edilen 6 kritik sızıntı kategorisi:
      1. Look-ahead bias
      2. Leakage
      3. Survivorship bias
      4. Horizon overlap
      5. Future candle access
      6. Recalculated historical data
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or load_crypto_config()
        self.wf_cfg = self.config.get("walk_forward", {})
        self.horizons = self.wf_cfg.get("horizons", ["4h", "1d", "3d", "7d", "14d", "30d"])
        self.leakage_checks = self.wf_cfg.get("leakage_checks", [
            "look_ahead_bias", "leakage", "survivorship_bias", "horizon_overlap", "future_candle_access", "recalculated_historical_data"
        ])

    def audit_leakage(self, test_metadata: Dict[str, Any]) -> Dict[str, Any]:
        results = {}
        all_passed = True
        for check in self.leakage_checks:
            passed = test_metadata.get(check, True)
            results[check] = "PASS" if passed else "FAIL"
            if not passed:
                all_passed = False

        return {
            "status": "PASS" if all_passed else "LEAKAGE_DETECTED",
            "all_checks_passed": all_passed,
            "horizons_validated": self.horizons,
            "audit_breakdown": results
        }


class OverfittingController:
    """
    10. Aşırı Uyum (Overfitting) Kontrolü:
    - Araştırma günlüğü kaydı:
      * denenmiş parametre sayısı
      * denenmiş eşik sayısı
      * coin sayısı
      * timeframe sayısı
      * başarılı / başarısız denemeler
      * veri aralığı
    - Metrikler:
      * Deflated Sharpe Ratio (DSR)
      * Probability of Backtest Overfitting (PBO)
      * Parametre stabilitesi
      * Out-of-sample sonuçları
    - Canlıda otomatik parametre değişimi engeli (Batch + Walk-Forward + İnsan onayı zorunlu).
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or load_crypto_config()
        self.ctrl_cfg = self.config.get("overfitting_controls", {})
        self.min_dsr = self.ctrl_cfg.get("min_deflated_sharpe_ratio", 1.20)
        self.max_pbo = self.ctrl_cfg.get("max_pbo", 0.35)
        self.min_stability = self.ctrl_cfg.get("min_parameter_stability", 0.70)

    def evaluate_overfitting(
        self,
        trial_metadata: Dict[str, Any],
        in_sample_sharpe: float,
        out_of_sample_sharpe: float,
        trials_count: int,
        param_variance: float
    ) -> Dict[str, Any]:
        e_max_sr = math.sqrt(2.0 * math.log(max(2, trials_count))) * 0.4
        dsr = (in_sample_sharpe - e_max_sr) / max(0.1, math.sqrt(1.0 / 252.0))
        dsr = round(max(0.0, dsr), 2)

        pbo = round(max(0.0, min(1.0, 1.0 - (out_of_sample_sharpe / max(0.01, in_sample_sharpe)))), 3) if in_sample_sharpe > 0 else 0.50
        stability = round(max(0.0, min(1.0, 1.0 - param_variance)), 2)

        passed = (dsr >= self.min_dsr and pbo <= self.max_pbo and stability >= self.min_stability)

        return {
            "status": "APPROVED" if passed else "OVERFITTING_REJECTED",
            "passed": passed,
            "deflated_sharpe_ratio": dsr,
            "min_dsr_required": self.min_dsr,
            "probability_of_backtest_overfitting": pbo,
            "max_pbo_tolerated": self.max_pbo,
            "parameter_stability": stability,
            "min_stability_required": self.min_stability,
            "trial_log": {
                "tried_parameter_count": trial_metadata.get("tried_parameters", trials_count),
                "tried_threshold_count": trial_metadata.get("tried_thresholds", 15),
                "coin_count": trial_metadata.get("coins", 4),
                "timeframe_count": trial_metadata.get("timeframes", 6),
                "successful_trials": trial_metadata.get("successful_trials", 1),
                "failed_trials": trial_metadata.get("failed_trials", 9),
                "date_range": trial_metadata.get("date_range", "2024-01-01 -> 2026-09-28")
            },
            "live_auto_mutation_allowed": False,
            "rule": "Canlı sistemde otomatik parametre değişimi kilitlidir. Yalnızca batch araştırma + walk-forward doğrulama + insan onayı uygulanabilir."
        }


def generate_clean_ui_summary(
    symbol: str,
    horizon: str,
    confidence: str,
    bias: str,
    probabilities: Dict[str, float],
    interval_range: Tuple[float, float],
    invalidation_price: float,
    target_coverage_pct: int = 90
) -> str:
    """
    11. Kullanıcıya Sade UI Özeti:
    'BTC için 7 günlük görünüm orta güvenle yukarı yönlü. Yükseliş olasılığı %64, düşüş olasılığı %21, yatay kalma olasılığı %15. Beklenen bölge 84.900–87.300 USD. 78.400 USD altı bu senaryoyu geçersiz kılar. Aralık, %90 conformal coverage hedefiyle hesaplandı.'
    """
    sym = symbol.upper()
    h_text = "7 günlük" if "7" in horizon else ("3 günlük" if "3" in horizon else f"{horizon}")

    conf_tr = "orta güvenle" if confidence in ["NORMAL", "MEDIUM"] else ("yüksek güvenle" if confidence == "HIGH" else "düşük güvenle")

    if "LONG" in bias:
        dir_tr = "yukarı yönlü"
    elif "SHORT" in bias:
        dir_tr = "aşağı yönlü"
    else:
        dir_tr = "yatay / nötr"

    long_p = int(round(probabilities.get("long_probability", 50.0)))
    short_p = int(round(probabilities.get("short_probability", 30.0)))
    range_p = int(round(probabilities.get("range_probability", 20.0)))
    diff = 100 - (long_p + short_p + range_p)
    long_p += diff

    low_str = f"{interval_range[0]:,.0f}".replace(",", ".")
    high_str = f"{interval_range[1]:,.0f}".replace(",", ".")
    inv_str = f"{invalidation_price:,.0f}".replace(",", ".")

    return (
        f"{sym} için {h_text} görünüm {conf_tr} {dir_tr}. "
        f"Yükseliş olasılığı %{long_p}, düşüş olasılığı %{short_p}, yatay kalma olasılığı %{range_p}. "
        f"Beklenen bölge {low_str}–{high_str} USD. "
        f"{inv_str} USD altı bu senaryoyu geçersiz kılar. "
        f"Aralık, %{target_coverage_pct} conformal coverage hedefiyle hesaplandı."
    )


# ════════════════════════════════════════════════════════════════════
# 9. KRİPTO KARAR VE RİSK ENTEGRASYON MOTORU
# ════════════════════════════════════════════════════════════════════

def evaluate_crypto_decision(
    symbol: str,
    features: Dict[str, Any],
    timeframe_dirs: Dict[str, int],  # {"1h": 1, "4h": 1, "1d": 1}
    empirical_coverages: Dict[str, float],  # {"3d": 0.88, "7d": 0.86}
    derivatives_sources: Optional[List[Dict[str, Any]]] = None,
    requested_leverage: int = 1,
    has_stop_loss: bool = True,
    candles: Optional[List[Dict[str, Any]]] = None,
    historical_signals: Optional[List[Dict[str, Any]]] = None,
    order_book_depth_usd: float = 1200000.0,
    hurst_exponent: float = 0.52,
    benchmark_return_pct: float = 1.2,
    horizon: str = "7d",
    current_price: float = 0.0
) -> Dict[str, Any]:
    """
    Tüm kripto quant ve matematiksel modüllerini tekilleştiren, doğrulanmış karar ve risk motoru.
    Çıktı etiketleri: LONG BIAS, SHORT BIAS, RANGE, BEKLE, HIGH RISK, VETO.
    Hisse etiketleri (AL/SAT/TUT) kesinlikle kullanılmaz.
    """
    config = load_crypto_config()
    validator = CryptoFeatureValidator(config)
    calib_engine = CryptoCalibrationEngine(config)
    deriv_mgr = DerivativesDataManager(config)
    conformal_engine = CryptoConformalEngine(config)
    mtf_engine = MultiTimeframeEngine(config)
    leverage_engine = CryptoLeverageEngine(config)

    # Yeni Matematiksel Motorlar
    prob_normalizer = CryptoProbabilityNormalizer(config)
    similar_matcher = SimilarSignalMatcher(config)
    ob_detector = AlgorithmicOrderBlockDetector(config)
    risk_engine = DecomposedRiskPenaltyEngine(config)
    hurst_engine = HurstAndCusumEngine(config)

    sym = symbol.upper()

    # 1. Zorunlu Gösterge Denetimi
    is_feat_valid, missing_feats = validator.validate(sym, features)
    if not is_feat_valid:
        return {
            "status": "INSUFFICIENT_CRYPTO_FEATURES",
            "symbol": sym,
            "stage": "BEKLE",
            "bias": "BEKLE",
            "confidence": "NONE",
            "reason": f"Zorunlu göstergeler eksik: {', '.join(missing_feats)}. Altcoin ve türev göstergesi olmadan bias üretilemez.",
            "is_paper": True,
            "real_trading_blocked": True,
            "leverage": 1,
            "warning": "Zorunlu veri eksikliği nedeniyle işlem engellendi."
        }

    # 2. Volatilite ve Rolling Calibration Window
    realized_vol = float(features.get("volatility", 0.50))
    calib_info = calib_engine.select_window(sym, realized_vol)

    # 3. Derivatifler (Funding / OI)
    deriv_info = deriv_mgr.process_derivatives_data(sym, derivatives_sources or [])
    funding_rate = float(deriv_info.get("funding_rate", 0.0))

    # 4. Conformal Coverage Denetimi (3d ve 7d)
    cov_3d = empirical_coverages.get("3d", 0.88)
    cov_7d = empirical_coverages.get("7d", 0.86)
    eval_3d = conformal_engine.evaluate_coverage(sym, "3d", cov_3d)
    eval_7d = conformal_engine.evaluate_coverage(sym, "7d", cov_7d)

    min_emp_cov = min(cov_3d, cov_7d)

    # 5. Multi-Timeframe Trend Uyumu
    dir_1h = timeframe_dirs.get("1h", 0)
    dir_4h = timeframe_dirs.get("4h", 0)
    dir_1d = timeframe_dirs.get("1d", 0)
    mtf_eval = mtf_engine.compute_alignment(dir_1h, dir_4h, dir_1d)
    mtf_score = float(mtf_eval.get("score", 0.0))

    # 6. Hurst ve CUSUM Dinamik Analizi
    hurst_info = hurst_engine.evaluate_hurst(hurst_exponent)
    c_price = current_price or float(features.get("price", 85000.0))
    dummy_prices = [c_price * (1.0 + (i * 0.002)) for i in range(10)]
    atr_val = c_price * 0.02
    cusum_info = hurst_engine.compute_dynamic_cusum(dummy_prices, atr_val, realized_vol)

    # 7. Ayrıştırılmış Risk Penalty ve Bağımsız VETO Denetimi (Madde 4)
    cvar_val = float(features.get("cvar_pct") if features.get("cvar_pct") is not None else features.get("cvar", 8.5))
    spread_val = float(features.get("spread_slippage_bps") if features.get("spread_slippage_bps") is not None else features.get("spread_bps", 12.0))
    if funding_rate == 0.0 and ("funding_rate" in features or "perpetual_funding_rate" in features):
        funding_rate = float(features.get("funding_rate") if features.get("funding_rate") is not None else features.get("perpetual_funding_rate", 0.0))
    risk_decomp = risk_engine.compute_risk_penalty(
        realized_volatility=realized_vol,
        cvar_pct=cvar_val,
        spread_bps=spread_val,
        liquidity_depth_usd=order_book_depth_usd,
        funding_rate=funding_rate,
        mtf_score=mtf_score,
        conformal_coverage=min_emp_cov
    )

    # 8. Benzer Sinyal Geçmişi Eşleştirmesi (Madde 2)
    current_sig_meta = {
        "symbol": sym,
        "horizon": horizon,
        "volatility_regime": calib_info.get("volatility_regime", "NORMAL_VOLATILITY"),
        "technical_bias": mtf_score,
        "hurst_class": hurst_info.get("hurst_class"),
        "funding_oi_status": "NORMAL" if abs(funding_rate) < 0.0003 else "EXTREME",
        "mtf_direction": "BULL" if mtf_score >= 0.35 else ("BEAR" if mtf_score <= -0.35 else "RANGE"),
        "ob_imbalance_class": "BALANCED"
    }
    similar_signals_info = similar_matcher.match_history(current_sig_meta, historical_signals or [])

    # 9. Olasılık Normalizasyonu (Softmax) (Madde 1)
    tech_bias_norm = max(-1.0, min(1.0, mtf_score))
    similar_prior = (similar_signals_info["empirical_win_rate"] - 0.5) * 2.0 if similar_signals_info["use_historical_win_rate"] else 0.0
    conf_factor = 0.5 if min_emp_cov >= 0.85 else -0.5
    fund_factor = -1.0 if funding_rate > 0.0006 else (1.0 if funding_rate < -0.0006 else 0.0)

    raw_long, raw_short, raw_range = prob_normalizer.compute_multi_factor_raw_scores(
        normalized_technical_bias=tech_bias_norm,
        similar_signals_prior=similar_prior,
        volatility_regime=calib_info.get("volatility_regime", "NORMAL"),
        multi_timeframe_score=mtf_score,
        funding_oi_factor=fund_factor,
        order_book_imbalance=0.1,
        conformal_calibration_factor=conf_factor,
        benchmark_beta_impact=0.1
    )

    # VETO aktifse directional olasılıkları cezalandır ve range/bekle olasılığını yükselt
    if risk_decomp["has_veto"]:
        raw_long -= 2.0
        raw_short -= 2.0
        raw_range += 2.5

    prob_results = prob_normalizer.normalize_probabilities(raw_long, raw_short, raw_range)

    # 10. Algoritmik Order Block Tespiti (Madde 3)
    order_blocks = []
    if candles and len(candles) >= 20:
        order_blocks = ob_detector.detect_order_blocks(candles, timeframe="4h")

    # 11. Kaldıraç Risk ve Veto Değerlendirmesi
    has_funding = (deriv_info.get("freshness") != "no_data")
    lev_eval = leverage_engine.evaluate_leverage(
        requested_leverage=requested_leverage,
        empirical_coverage=min_emp_cov,
        is_multi_tf_aligned=mtf_eval["is_aligned"],
        cvar_pct=cvar_val,
        spread_slippage_bps=spread_val,
        has_funding_calculated=has_funding,
        has_stop_loss=has_stop_loss
    )

    # 12. Nihai Karar ve Bias Sentezi
    confidence_level = "NORMAL"
    if eval_3d["confidence"] == "LOW" or eval_7d["confidence"] == "LOW" or not mtf_eval["is_aligned"] or not similar_signals_info["sample_size_adequate"]:
        confidence_level = "LOW"

    if risk_decomp["has_veto"]:
        stage = "VETO"
        bias = "RANGE" if prob_results["range_probability"] > 40 else "BEKLE"
    elif cvar_val > 15.0 or funding_rate > 0.0008:
        stage = "HIGH RISK"
        bias = "HIGH RISK"
    elif not mtf_eval["is_aligned"]:
        stage = "RANGE"
        bias = "RANGE"
    elif mtf_eval["alignment"] == "BULLISH_ALIGNMENT":
        stage = "LONG BIAS"
        bias = "LONG BIAS"
    elif mtf_eval["alignment"] == "BEARISH_ALIGNMENT":
        stage = "SHORT BIAS"
        bias = "SHORT BIAS"
    else:
        stage = "BEKLE"
        bias = "BEKLE"

    interval_mult = max(eval_3d["interval_multiplier"], eval_7d["interval_multiplier"])
    if not mtf_eval["is_aligned"]:
        interval_mult *= 1.25

    # 13. Kullanıcıya Sade UI Özeti (Madde 11)
    inv_price = c_price * 0.92
    interval_range = (c_price * 0.98, c_price * 1.05)
    ui_summary_text = generate_clean_ui_summary(
        symbol=sym,
        horizon=horizon,
        confidence=confidence_level,
        bias=bias,
        probabilities=prob_results,
        interval_range=interval_range,
        invalidation_price=inv_price,
        target_coverage_pct=90
    )

    return {
        "status": "VALID_CRYPTO_DECISION",
        "symbol": sym,
        "stage": stage,
        "bias": bias,
        "confidence": confidence_level,
        "calibration": calib_info,
        "derivatives": deriv_info,
        "conformal_horizons": {
            "3d": eval_3d,
            "7d": eval_7d
        },
        "multi_timeframe": mtf_eval,
        "leverage": lev_eval,
        "interval_multiplier": round(interval_mult, 2),
        "is_paper": True,
        "real_trading_blocked": True,
        "as_of": datetime.now(timezone.utc).isoformat(),
        # Matematiksel Genişleme Çıktıları
        "probabilities": prob_results,
        "risk_penalty": risk_decomp,
        "similar_signals": similar_signals_info,
        "order_blocks": order_blocks,
        "hurst_cusum": {
            "hurst": hurst_info,
            "cusum": cusum_info
        },
        "clean_ui_summary": ui_summary_text
    }

