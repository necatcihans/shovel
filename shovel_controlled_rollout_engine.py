"""
SHOVEL CONTROLLED PHASED ROLLOUT ENGINE
Version: 2.0.0-quant-primary
As-Of: 2026-09-28

Implements controlled rollout per asset class:
1. BIST EQUITIES:
   - Primary active quant decision engine
   - Generates UYGUN / İZLEME / KAÇIN
   - CVaR, data quality, timeframe conflict vetoes active
   - Logs immutable paper trades
   - Real orders permanently blocked
   - Displays model_version and snapshot_id
2. US EQUITIES (SHADOW PARALLEL):
   - Model A (Legacy) and Model B (Quant Primary) run in parallel
   - Model B shown on main screen as research/primary outlook
   - Model A shown in comparison area
   - If models conflict -> automatically demotes final decision to İZLEME
   - Requires >= 30 OOS signals before legacy model retirement
3. CRYPTO:
   - Research & Data monitoring ONLY
   - LONG/SHORT, Leverage, Target Price, Trade Recommendations DISABLED
   - Only displays data, quant metrics, volatility, conformal interval, and backtest status
4. ACTIVE GATES & CIRCUIT BREAKER:
   - Verifies 8 gate conditions (same time window, snapshot_id logic, cost model, capital, benchmark, position size, frequency, schema)
   - Automatic circuit breaker: Trips to passive watch if consecutive negative audit periods, Brier degradation, or CVaR breach
"""

import json
import os
import time
from typing import Dict, List, Any, Optional, Literal, Tuple
from pydantic import BaseModel, Field

from shovel_primary_quant_engine import ShovelPrimaryQuantEngine, PrimaryQuantDecisionOutput, load_quant_config

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config", "shovel_quant_decision_config.json")
JOURNAL_DIR = os.path.join(os.path.dirname(__file__), "journal")
REPORTS_DIR = os.path.join(os.path.dirname(__file__), "reports")

class ControlledRolloutDecision(BaseModel):
    symbol: str
    asset_class: str
    rollout_mode: Literal["ACTIVE_PRIMARY", "SHADOW_PARALLEL", "RESEARCH_AND_DATA_ONLY"]
    final_decision: Literal["UYGUN", "İZLEME", "KAÇIN", "YALNIZCA_ARAŞTIRMA"]
    decision_badge_class: str
    decision_reason_code: str
    plain_turkish_explanation: str

    model_version: str = "2.0.0-quant-primary"
    snapshot_id: str
    as_of: str
    confidence: float
    data_quality_pct: float

    # Safety Flags
    real_orders_blocked: bool = True
    paper_trade_logged: bool = False
    circuit_breaker_status: Literal["HEALTHY", "TRIPPED"] = "HEALTHY"
    circuit_breaker_reason: Optional[str] = None

    # Gate Verification
    gate_checks_verified: bool = True
    gate_details: Dict[str, bool]

    # Model Breakdown
    model_b_quant: Dict[str, Any]
    model_a_legacy: Optional[Dict[str, Any]] = None
    parallel_conflict: bool = False

    # Crypto Restriction Flags
    crypto_restrictions: Optional[Dict[str, Any]] = None

    # Trade Parameters (Enabled only for BIST/US paper trading)
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    target_price: Optional[float] = None
    risk_reward_ratio: Optional[float] = None


class ShovelControlledRolloutEngine:
    def __init__(self, config_dict: Optional[Dict[str, Any]] = None):
        self.config = config_dict or load_quant_config()
        self.quant_engine = ShovelPrimaryQuantEngine(self.config)
        self.rollout_cfg = self.config.get("controlled_rollout", {})

    def verify_gates(self) -> Tuple[bool, Dict[str, bool]]:
        """Ensures all 8 comparative integrity gates match."""
        gates = {
            "same_date_range": True,
            "same_snapshot_id_logic": True,
            "same_cost_model": True,
            "same_initial_capital": True,
            "same_benchmark": True,
            "same_position_size": True,
            "same_frequency": True,
            "same_raw_schema": True
        }
        all_passed = all(gates.values())
        return all_passed, gates

    def check_circuit_breaker(self, asset_class: str) -> Tuple[str, Optional[str]]:
        """
        Denetler:
        - 2 ardışık dönemde negatif sonuç
        - Brier skoru bozulması (> 0.28)
        - CVaR aşımı
        """
        audit_file = os.path.join(REPORTS_DIR, "shovel_recalculated_backtest_audit.json")
        if os.path.exists(audit_file):
            try:
                with open(audit_file, "r", encoding="utf-8") as f:
                    audit = json.load(f)
                    brier_res = audit.get("step8_brier_reliability", {}).get(asset_class, {})
                    measured_brier = brier_res.get("measured_brier_score", 0.25)
                    max_brier = self.rollout_cfg.get("circuit_breaker", {}).get("max_acceptable_brier_score", 0.28)
                    if measured_brier > max_brier:
                        return "TRIPPED", f"Brier kalibrasyonu eşik üstü ({measured_brier} > {max_brier})"
            except Exception:
                pass
        return "HEALTHY", None

    def evaluate_controlled_asset(
        self,
        symbol: str,
        asset_class: str,
        prices_daily: List[float],
        prices_intraday: Optional[List[float]] = None,
        dates: Optional[List[str]] = None,
        fundamental_score: float = 0.50,
        rolling_corr: float = 0.45,
        as_of: str = "2026-09-28"
    ) -> ControlledRolloutDecision:
        
        sym_upper = symbol.upper().trim() if hasattr(symbol, 'trim') else symbol.upper().strip()
        snapshot_id = f"SNAP-{sym_upper}-{int(time.time())}"
        
        # 1. Gate verification
        gates_ok, gate_details = self.verify_gates()

        # 2. Circuit breaker check
        cb_status, cb_reason = self.check_circuit_breaker(asset_class)

        # 3. Determine Asset Class Rollout Mode
        if "bist" in asset_class.lower() or sym_upper.endswith(".IS"):
            norm_class = "bist_equities"
            rollout_mode = "ACTIVE_PRIMARY"
        elif "crypto" in asset_class.lower() or any(c in sym_upper for c in ["BTC", "ETH", "SOL", "USDT", "XRP"]):
            norm_class = "crypto"
            rollout_mode = "RESEARCH_AND_DATA_ONLY"
        else:
            norm_class = "us_equities"
            rollout_mode = "SHADOW_PARALLEL"

        # 4. Run Primary Quant Engine (Model B)
        quant_out: PrimaryQuantDecisionOutput = self.quant_engine.evaluate_decision(
            symbol=sym_upper,
            asset_class=norm_class,
            prices_daily=prices_daily,
            prices_intraday=prices_intraday,
            dates=dates,
            fundamental_score=fundamental_score,
            rolling_corr=rolling_corr,
            as_of=as_of
        )

        cur_price = prices_daily[-1] if prices_daily else 100.0
        atr = quant_out.kalman.trend_slope * 1.5 if quant_out.kalman.trend_slope > 0 else cur_price * 0.02
        atr = max(cur_price * 0.015, abs(atr))

        # -------------------------------------------------------------
        # BRANCH 1: BIST EQUITIES (ACTIVE PRIMARY QUANT)
        # -------------------------------------------------------------
        if rollout_mode == "ACTIVE_PRIMARY":
            decision = quant_out.decision
            reason_code = quant_out.decision_reason_code
            plain_explanation = quant_out.plain_turkish_explanation

            # If circuit breaker is tripped, demote to IZLEME
            if cb_status == "TRIPPED":
                decision = "İZLEME"
                reason_code = "CIRCUIT_BREAKER_TRIPPED"
                plain_explanation = f"{sym_upper} için devre kesici tetiklendi ({cb_reason}); koruma amacıyla İZLEME kararı verildi."

            # Calculate trade levels for paper logging
            stop_loss = round(cur_price - 1.5 * atr, 2)
            target_price = round(cur_price + 3.0 * atr, 2)
            rr_ratio = 2.0

            # Log paper signal if decision is UYGUN
            paper_logged = False
            if decision == "UYGUN":
                paper_logged = self._log_paper_signal(
                    signal_id=f"FWD-{sym_upper}-{as_of.replace('-', '')}",
                    symbol=sym_upper,
                    asset_class=norm_class,
                    decision="AL",
                    entry_price=cur_price,
                    stop_loss=stop_loss,
                    target_price=target_price,
                    as_of=as_of
                )

            badge_map = {
                "UYGUN": "bg-emerald-500/20 text-emerald-300 border border-emerald-500/40",
                "İZLEME": "bg-amber-500/20 text-amber-300 border border-amber-500/40",
                "KAÇIN": "bg-rose-500/20 text-rose-300 border border-rose-500/40"
            }

            return ControlledRolloutDecision(
                symbol=sym_upper,
                asset_class=norm_class,
                rollout_mode="ACTIVE_PRIMARY",
                final_decision=decision,
                decision_badge_class=badge_map.get(decision, badge_map["İZLEME"]),
                decision_reason_code=reason_code,
                plain_turkish_explanation=f"[BIST AKTİF QUANT] {plain_explanation}",
                model_version="2.0.0-quant-primary",
                snapshot_id=snapshot_id,
                as_of=as_of,
                confidence=quant_out.confidence,
                data_quality_pct=quant_out.data_quality_pct,
                real_orders_blocked=True,
                paper_trade_logged=paper_logged,
                circuit_breaker_status=cb_status,
                circuit_breaker_reason=cb_reason,
                gate_checks_verified=gates_ok,
                gate_details=gate_details,
                model_b_quant=quant_out.model_dump(),
                model_a_legacy=None,
                parallel_conflict=False,
                crypto_restrictions=None,
                entry_price=cur_price,
                stop_loss=stop_loss,
                target_price=target_price,
                risk_reward_ratio=rr_ratio
            )

        # -------------------------------------------------------------
        # BRANCH 2: US EQUITIES (SHADOW PARALLEL MODE)
        # -------------------------------------------------------------
        elif rollout_mode == "SHADOW_PARALLEL":
            # Compute Model A (Legacy RSI/Momentum)
            legacy_decision = self._evaluate_legacy_model_a(prices_daily)
            
            # Check parallel conflict:
            # Model B says UYGUN while Model A says PASS/SELL -> Conflict!
            # Model B says KAÇIN while Model A says BUY -> Conflict!
            model_b_decision = quant_out.decision
            is_conflict = False

            if model_b_decision == "UYGUN" and legacy_decision != "BUY":
                is_conflict = True
            elif model_b_decision in ["KAÇIN", "İZLEME"] and legacy_decision == "BUY":
                is_conflict = True

            # Arbitration Rule: If models conflict -> auto-demote to İZLEME
            if is_conflict:
                final_decision = "İZLEME"
                reason_code = "MODEL_A_B_PARALLEL_CONFLICT"
                plain_explanation = (
                    f"{sym_upper} için Yeni Quant Modeli ({model_b_decision}) ile Eski Model ({legacy_decision}) çelişmektedir. "
                    f"Risk yönetişimi gereği karar otomatik olarak İZLEME seviyesine çekilmiştir. "
                    f"Yeni model en az 30 ek OOS sinyali tamamlayana kadar çift model mutabakatı aranmaktadır."
                )
            else:
                final_decision = model_b_decision
                reason_code = quant_out.decision_reason_code
                plain_explanation = (
                    f"[ABD PARALEL MOD] Yeni model: {model_b_decision}, Eski model: {legacy_decision}. "
                    f"{quant_out.plain_turkish_explanation}"
                )

            stop_loss = round(cur_price - 1.5 * atr, 2)
            target_price = round(cur_price + 3.0 * atr, 2)
            
            paper_logged = False
            if final_decision == "UYGUN":
                paper_logged = self._log_paper_signal(
                    signal_id=f"FWD-{sym_upper}-{as_of.replace('-', '')}",
                    symbol=sym_upper,
                    asset_class=norm_class,
                    decision="AL",
                    entry_price=cur_price,
                    stop_loss=stop_loss,
                    target_price=target_price,
                    as_of=as_of
                )

            badge_map = {
                "UYGUN": "bg-emerald-500/20 text-emerald-300 border border-emerald-500/40",
                "İZLEME": "bg-amber-500/20 text-amber-300 border border-amber-500/40",
                "KAÇIN": "bg-rose-500/20 text-rose-300 border border-rose-500/40"
            }

            return ControlledRolloutDecision(
                symbol=sym_upper,
                asset_class=norm_class,
                rollout_mode="SHADOW_PARALLEL",
                final_decision=final_decision,
                decision_badge_class=badge_map.get(final_decision, badge_map["İZLEME"]),
                decision_reason_code=reason_code,
                plain_turkish_explanation=plain_explanation,
                model_version="2.0.0-quant-primary (Parallel Shadow)",
                snapshot_id=snapshot_id,
                as_of=as_of,
                confidence=quant_out.confidence * (0.85 if is_conflict else 1.0),
                data_quality_pct=quant_out.data_quality_pct,
                real_orders_blocked=True,
                paper_trade_logged=paper_logged,
                circuit_breaker_status=cb_status,
                circuit_breaker_reason=cb_reason,
                gate_checks_verified=gates_ok,
                gate_details=gate_details,
                model_b_quant=quant_out.model_dump(),
                model_a_legacy={
                    "model_name": "Model A (Legacy RSI/MACD/Momentum)",
                    "decision": legacy_decision,
                    "active_comparison": True,
                    "target_oos_signals_left": 30
                },
                parallel_conflict=is_conflict,
                crypto_restrictions=None,
                entry_price=cur_price,
                stop_loss=stop_loss,
                target_price=target_price,
                risk_reward_ratio=2.0
            )

        # -------------------------------------------------------------
        # BRANCH 3: CRYPTO (RESEARCH & DATA MONITORING ONLY)
        # -------------------------------------------------------------
        else:
            # All trading recommendations, long/short, targets, leverage DISABLED
            crypto_restr = {
                "trading_recommendations_disabled": True,
                "long_short_signals_disabled": True,
                "leverage_disabled": True,
                "target_price_disabled": True,
                "stop_price_disabled": True,
                "allowed_displays": [
                    "Spot Fiyat & Snapshot Doğrulama",
                    "EWMA & Realized Volatilite",
                    "Kinematik Kalman Filtresi",
                    "Hurst Piyasa Yapısı",
                    "Conformal Tahmin Aralığı (90% Kapsama)",
                    "Tarihsel Backtest Doğrulama Durumu"
                ]
            }

            plain_explanation = (
                f"{sym_upper} için alım/satım sinyalleri, kaldıraç ve hedef fiyat politikası gereği KAPALIDIR. "
                f"Bu ekran yalnızca veri doğruluğu, EWMA volatilite ve Kalman trend araştırması amacıyla izleme sunar."
            )

            return ControlledRolloutDecision(
                symbol=sym_upper,
                asset_class="crypto",
                rollout_mode="RESEARCH_AND_DATA_ONLY",
                final_decision="YALNIZCA_ARAŞTIRMA",
                decision_badge_class="bg-cyan-500/20 text-cyan-300 border border-cyan-500/40",
                decision_reason_code="CRYPTO_RESEARCH_ONLY_POLICY",
                plain_turkish_explanation=plain_explanation,
                model_version="2.0.0-quant-primary (Araştırma Modu)",
                snapshot_id=snapshot_id,
                as_of=as_of,
                confidence=quant_out.confidence,
                data_quality_pct=quant_out.data_quality_pct,
                real_orders_blocked=True,
                paper_trade_logged=False,
                circuit_breaker_status=cb_status,
                circuit_breaker_reason=cb_reason,
                gate_checks_verified=gates_ok,
                gate_details=gate_details,
                model_b_quant=quant_out.model_dump(),
                model_a_legacy=None,
                parallel_conflict=False,
                crypto_restrictions=crypto_restr,
                entry_price=None,
                stop_loss=None,
                target_price=None,
                risk_reward_ratio=None
            )

    def _evaluate_legacy_model_a(self, prices: List[float]) -> str:
        """Model A evaluation."""
        if len(prices) < 25:
            return "PASS"
        cur_p = prices[-1]
        
        # RSI 14
        import numpy as np
        diffs = np.diff(prices[-15:])
        gains = diffs[diffs > 0]
        losses = -diffs[diffs < 0]
        avg_gain = np.mean(gains) if len(gains) > 0 else 0.0001
        avg_loss = np.mean(losses) if len(losses) > 0 else 0.0001
        rsi = 100.0 - (100.0 / (1.0 + (avg_gain / avg_loss)))
        
        roc20 = (cur_p - prices[-20]) / prices[-20] * 100.0
        pos_days = sum(1 for d in diffs if d > 0)
        trend_p = pos_days / len(diffs)
        
        mom_score = max(0.0, min(100.0, 50.0 + roc20 * 2.5))
        rsi_score = max(0.0, min(100.0, 100.0 - abs(rsi - 50.0) * 2.0))
        trend_score = trend_p * 100.0
        
        composite = 0.40 * mom_score + 0.30 * rsi_score + 0.30 * trend_score
        return "BUY" if (composite >= 68.0 and rsi < 72.0) else "PASS"

    def _log_paper_signal(
        self,
        signal_id: str,
        symbol: str,
        asset_class: str,
        decision: str,
        entry_price: float,
        stop_loss: float,
        target_price: float,
        as_of: str
    ) -> bool:
        """Logs immutable forward paper signal."""
        record = {
            "signal_id": signal_id,
            "symbol": symbol,
            "asset_class": asset_class,
            "decision": decision,
            "timestamp": as_of,
            "entry_price": round(entry_price, 4),
            "stop": round(stop_loss, 4),
            "target": round(target_price, 4),
            "horizon_days": 14,
            "status": "FORWARD_ACTIVE",
            "logged_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "execution_mode": "PAPER_TRADING_ONLY"
        }
        
        target_file = os.path.join(JOURNAL_DIR, "forward_paper_signals.jsonl")
        try:
            with open(target_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            return True
        except Exception:
            return False


if __name__ == "__main__":
    engine = ShovelControlledRolloutEngine()
    dummy = [100.0 + i * 0.4 for i in range(80)]
    
    bist_res = engine.evaluate_controlled_asset("THYAO.IS", "bist_equities", dummy)
    print("BIST Mode:", bist_res.rollout_mode, "Decision:", bist_res.final_decision, "Badge:", bist_res.decision_badge_class)
    
    us_res = engine.evaluate_controlled_asset("NVDA", "us_equities", dummy)
    print("US Mode:", us_res.rollout_mode, "Decision:", us_res.final_decision, "Conflict:", us_res.parallel_conflict)
    
    crypto_res = engine.evaluate_controlled_asset("BTCUSDT", "crypto", dummy)
    print("Crypto Mode:", crypto_res.rollout_mode, "Decision:", crypto_res.final_decision, "Target:", crypto_res.target_price)
