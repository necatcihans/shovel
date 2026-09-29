# -*- coding: utf-8 -*-
"""
shovel_decision_chain.py — Shovel Karar Sürümleme, Değişmez Karar Zinciri ve Canlı Paper Backtest Motoru

GÖREVLER:
1. Zaman içinde kararların (AL/TUT/SAT/İZLE) yeni snapshot'lar ile yeniden değerlendirilmesi (Decision Versioning).
2. Değişmez Kriptografik Hash Zinciri (Cryptographic Hash Chain): SHA-256 ile geriye dönük oynanamazlık doğrulaması.
3. Dinamik Benchmark Eşleme: ABD için SPY/QQQ, BIST için XU100, Kripto için BTC, Emtia için XAU.
4. Yapılandırılabilir Maliyet Modeli: Varlık sınıfı ve borsaya göre komisyon ve kayma (config/cost_models.json).
5. Canlı Piyasa Verisiyle Gerçek Zamanlı Paper Pozisyon Güncellemesi (Mark-to-Market, Stop/Hedef Tetikleyiciler).
6. Kesin Güvenlik Kilidi: REAL_TRADING_ENABLED = False (Zero Real Risk, Donanımlı Salt Okunur).
"""

from __future__ import annotations

import os
import sys
import json
import time
import hashlib
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple, Literal
from pydantic import BaseModel, Field

from shovel_governance import (
    DataConfidenceEvaluator, DataConfidenceState, CrossSourceAlignmentEngine,
    AltmanBeneishEvaluator, SignalDemoFilter, NautilusTraderBoundaryGuard,
    CONFIDENCE_UI_LABELS
)
from shovel_robust_quant import (
    RegimeEngine, TailRiskEngine, RobustStats
)

_global_regime_engine = RegimeEngine()

# UTF-8 stdout
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

VAULT_DIR = r"c:\Users\Cihan\Desktop\ikinci-beyin"
JOURNAL_DIR = os.path.join(VAULT_DIR, "journal")
CONFIG_DIR = os.path.join(VAULT_DIR, "config")
COST_MODELS_FILE = os.path.join(CONFIG_DIR, "cost_models.json")
DECISION_HISTORY_FILE = os.path.join(JOURNAL_DIR, "decision_history.jsonl")
PAPER_POSITIONS_FILE = os.path.join(JOURNAL_DIR, "paper_positions.jsonl")

# ════════════════════════════════════════════════════════════════════
# 0. KESİN VE DEĞİŞTİRİLEMEZ GÜVENLİK KİLİDİ (REAL TRADING ENFORCEMENT)
# ════════════════════════════════════════════════════════════════════

class _ImmutableSecurityGuard:
    """Gerçek işlem yapılmasını hem statik hem çalışma zamanında engelleyen güvenlik koruması."""
    def __init__(self):
        self._real_trading_enabled = False

    @property
    def REAL_TRADING_ENABLED(self) -> bool:
        return False

    @REAL_TRADING_ENABLED.setter
    def REAL_TRADING_ENABLED(self, value: Any):
        if value:
            raise PermissionError(
                "GERÇEK İŞLEM KESİNLİKLE ENGELLENDİ: Shovel mimarisinde REAL_TRADING_ENABLED "
                "değeri donanımlı olarak 'false' sabitlenmiştir. Gerçek borsa emir iletimi yasaktır."
            )

REAL_TRADING_GUARD = _ImmutableSecurityGuard()
REAL_TRADING_ENABLED: bool = False


# ════════════════════════════════════════════════════════════════════
# 1. DİNAMİK BENCHMARK VE MALİYET MODELİ KATMANI
# ════════════════════════════════════════════════════════════════════

BIST_SYMBOLS = {
    "THYAO", "EREGL", "ASELS", "GARAN", "BIMAS", "AKBNK", "KCHOL",
    "TUPRS", "SAHOL", "SISE", "ISCTR", "YKBNK", "PGSUS", "FROTO", "TOASO"
}

CRYPTO_SYMBOLS = {
    "BTC", "ETH", "SOL", "BNB", "XRP", "AVAX", "DOGE", "ADA", "DOT", "LINK", "MATIC"
}

COMMODITY_SYMBOLS = {
    "XAU", "XAG", "GOLD", "SILVER", "GLD", "SLV", "BRENT", "WTI"
}

DEFAULT_COST_MODELS = {
    "us_equities": {
        "commission_rate": 0.0002,
        "slippage_rate": 0.00015,
        "default_benchmark": "SPY",
        "benchmark_name": "S&P 500 ETF (SPY)"
    },
    "bist_equities": {
        "commission_rate": 0.0010,
        "slippage_rate": 0.0005,
        "default_benchmark": "XU100",
        "benchmark_name": "BIST 100 Endeksi (XU100)"
    },
    "crypto": {
        "commission_rate": 0.00075,
        "slippage_rate": 0.0005,
        "default_benchmark": "BTC",
        "benchmark_name": "Bitcoin (BTC)"
    },
    "commodities": {
        "commission_rate": 0.0005,
        "slippage_rate": 0.0002,
        "default_benchmark": "XAU",
        "benchmark_name": "Ons Altın (XAU)"
    },
    "default": {
        "commission_rate": 0.0003,
        "slippage_rate": 0.0002,
        "default_benchmark": "SPY",
        "benchmark_name": "S&P 500 (SPY)"
    }
}

def load_cost_models_config() -> Dict[str, Any]:
    """Harici yapılandırma dosyasından maliyet modellerini yükler."""
    if os.path.exists(COST_MODELS_FILE):
        try:
            with open(COST_MODELS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("markets", DEFAULT_COST_MODELS)
        except Exception:
            pass
    return DEFAULT_COST_MODELS

def resolve_asset_class(ticker: str) -> str:
    """Varlık sembolünden varlık sınıfını belirler."""
    t = ticker.upper().strip()
    if t.endswith(".IS") or t in BIST_SYMBOLS:
        return "bist_equities"
    if t in CRYPTO_SYMBOLS or t.endswith("-USD") or t.endswith("USDT") or t.startswith("BTC"):
        return "crypto"
    if t in COMMODITY_SYMBOLS:
        return "commodities"
    return "us_equities"

def resolve_benchmark(ticker: str) -> Tuple[str, str]:
    """
    Varlık sınıfına göre dinamik ve doğru benchmark belirler:
    - BIST: XU100 (BIST 100)
    - Kripto: BTC (Bitcoin)
    - Emtia: XAU (Ons Altın)
    - ABD: SPY (S&P 500)
    """
    asset_cls = resolve_asset_class(ticker)
    models = load_cost_models_config()
    market_cfg = models.get(asset_cls, models["default"])
    return market_cfg.get("default_benchmark", "SPY"), market_cfg.get("benchmark_name", "S&P 500")

def resolve_cost_model(ticker: str) -> Dict[str, float]:
    """Varlığa özel komisyon ve kayma (slippage) oranlarını döndürür."""
    asset_cls = resolve_asset_class(ticker)
    models = load_cost_models_config()
    cfg = models.get(asset_cls, models["default"])
    return {
        "commission_rate": float(cfg.get("commission_rate", 0.0002)),
        "slippage_rate": float(cfg.get("slippage_rate", 0.00015)),
        "benchmark_symbol": cfg.get("default_benchmark", "SPY"),
        "benchmark_name": cfg.get("benchmark_name", "S&P 500")
    }


# ════════════════════════════════════════════════════════════════════
# 2. KRİPTOGRAFİK HASH ZİNCİRİ FONKSİYONLARI (IMMUTABILITY)
# ════════════════════════════════════════════════════════════════════

GENESIS_HASH = "0" * 64

def compute_record_hash(prev_hash: str, payload: Dict[str, Any]) -> str:
    """
    Kayıt yükünü ve önceki hash'i kanonik (sıralı anahtarlarla) JSON haline getirip SHA-256 hash'ler.
    'record_hash' alanı hash hesabına dahil edilmez.
    """
    clean_payload = {k: v for k, v in payload.items() if k != "record_hash"}
    canonical_json = json.dumps(clean_payload, sort_keys=True, ensure_ascii=False)
    hasher = hashlib.sha256()
    hasher.update(prev_hash.encode("utf-8"))
    hasher.update(canonical_json.encode("utf-8"))
    return hasher.hexdigest()


# ════════════════════════════════════════════════════════════════════
# 3. VERİ SÖZLEŞMELERİ (PYDANTIC V2)
# ════════════════════════════════════════════════════════════════════

class DecisionVersionRecord(BaseModel):
    decision_id: str
    ticker: str
    decision_version: int
    previous_decision: Optional[str] = None
    new_decision: str
    changed_at: str
    change_reason: List[str] = Field(default_factory=list)
    snapshot_id: str
    model_version: str = "v4.2-core"
    data_as_of: str
    decision_source: str = "quant_harness"
    price: float
    quant_scores: Dict[str, Any] = Field(default_factory=dict)
    risk_status: str = "Normal"
    data_quality: str = "tam"
    data_confidence: str = "VALID"  # "VALID", "PARTIAL_CONFIDENCE", "INSUFFICIENT_DATA"
    ui_confidence_label: str = "Tam veri"
    is_technical_only: bool = False
    is_demo: bool = False
    signal_origin: str = "paper"  # "demo", "paper", "live_observation"
    altman_status: str = "included"  # "included", "warning_only", "excluded"
    beneish_status: str = "included"  # "included", "warning_only", "excluded"
    exclusion_reason: str = ""
    regime_state: str = "RISK_ON"
    tail_risk_metrics: Dict[str, Any] = Field(default_factory=dict)
    robust_scaling: Dict[str, Any] = Field(default_factory=dict)
    explanation: str = ""
    # Kriptografik Hash Zinciri Alanları
    prev_record_hash: str = GENESIS_HASH
    record_hash: str = ""


class PaperPositionRecord(BaseModel):
    position_id: str
    ticker: str
    signal_version: int
    status: str = "DEVAM EDİYOR"  # "DEVAM EDİYOR", "GERÇEKLEŞEN", "VERİ BEKLENİYOR"
    entry_price: float
    entry_time: str
    exit_price: Optional[float] = None
    exit_time: Optional[str] = None
    exit_reason: Optional[str] = None
    stop: Optional[float] = None
    target: Optional[float] = None
    target_horizon: str = "2–6 ay"
    position_size: float = 10000.0  # Sanal sermaye ($ veya TL)
    commission_rate: float = 0.0002
    slippage_rate: float = 0.00015
    current_price: float
    benchmark_symbol: str = "SPY"
    benchmark_name: str = "S&P 500"
    benchmark_entry_price: float = 500.0
    benchmark_current_price: float = 500.0
    realized_return_pct: Optional[float] = None
    unrealized_return_pct: float = 0.0
    benchmark_return_pct: float = 0.0
    alpha_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    r_multiple: float = 0.0
    is_paper: bool = True
    is_demo: bool = False
    signal_origin: str = "paper"  # "demo", "paper", "live_observation"
    data_confidence: str = "VALID"
    real_trading_blocked: bool = True
    # Kriptografik Hash Zinciri Alanları
    prev_record_hash: str = GENESIS_HASH
    record_hash: str = ""


# ════════════════════════════════════════════════════════════════════
# 4. DEĞİŞMEZ KARAR GEÇMİŞİ YÖNETİCİSİ (DECISION JOURNAL)
# ════════════════════════════════════════════════════════════════════

class DecisionJournal:
    def __init__(self, log_file: str = DECISION_HISTORY_FILE):
        self.log_file = log_file
        os.makedirs(os.path.dirname(self.log_file), exist_ok=True)

    def load_all(self) -> List[DecisionVersionRecord]:
        records = []
        if not os.path.exists(self.log_file):
            return records
        with open(self.log_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        data = json.loads(line)
                        records.append(DecisionVersionRecord(**data))
                    except Exception:
                        pass
        return records

    def get_ticker_history(self, ticker: str) -> List[DecisionVersionRecord]:
        all_rec = self.load_all()
        return [r for r in all_rec if r.ticker.upper() == ticker.upper()]

    def get_latest_decision(self, ticker: str) -> Optional[DecisionVersionRecord]:
        history = self.get_ticker_history(ticker)
        if not history:
            return None
        return history[-1]

    def append_decision(self, record: DecisionVersionRecord) -> bool:
        # İmmutability denetimi: Aynı snapshot daha önce kaydedilmişse reddet
        history = self.get_ticker_history(record.ticker)
        for h in history:
            if h.snapshot_id == record.snapshot_id:
                return False
            if h.decision_id == record.decision_id:
                return False

        all_records = self.load_all()
        prev_hash = all_records[-1].record_hash if all_records and all_records[-1].record_hash else GENESIS_HASH
        
        record.prev_record_hash = prev_hash
        payload_dict = record.model_dump()
        record.record_hash = compute_record_hash(prev_hash, payload_dict)

        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record.model_dump(), ensure_ascii=False) + "\n")
        return True

    def verify_chain_integrity(self) -> Dict[str, Any]:
        """
        Kriptografik SHA-256 hash zincirini baştan sona denetler.
        Herhangi bir satır değiştirilmiş, silinmiş veya eklenmişse hata bildirir.
        """
        records = self.load_all()
        if not records:
            return {"valid": True, "count": 0, "message": "Zincir boş (Genesis durumunda)"}

        expected_prev_hash = GENESIS_HASH
        for idx, rec in enumerate(records):
            # 1. Önceki hash uyuşuyor mu?
            if rec.prev_record_hash != expected_prev_hash:
                return {
                    "valid": False,
                    "tampered_index": idx,
                    "decision_id": rec.decision_id,
                    "error": f"Kayıt {idx} prev_record_hash uyuşmazlığı: Beklenen {expected_prev_hash[:16]}..., Bulunan {rec.prev_record_hash[:16]}..."
                }

            # 2. Mevcut kayıt hash'i yeniden hesaplandığında tutuyor mu?
            calculated_hash = compute_record_hash(expected_prev_hash, rec.model_dump())
            if rec.record_hash != calculated_hash:
                return {
                    "valid": False,
                    "tampered_index": idx,
                    "decision_id": rec.decision_id,
                    "error": f"Kayıt {idx} yükü tahrif edilmiş (Tampering detected)! Kayıtlı: {rec.record_hash[:16]}..., Hesaplanan: {calculated_hash[:16]}..."
                }

            expected_prev_hash = rec.record_hash

        return {
            "valid": True,
            "count": len(records),
            "latest_record_hash": expected_prev_hash,
            "message": "Kriptografik hash zinciri eksiksiz ve tahrifatsız doğrulandı."
        }


# ════════════════════════════════════════════════════════════════════
# 5. CANLI PAPER BACKTEST PORTFÖY YÖNETİCİSİ (PAPER PORTFOLIO)
# ════════════════════════════════════════════════════════════════════

class PaperPortfolio:
    def __init__(self, log_file: str = PAPER_POSITIONS_FILE):
        self.log_file = log_file
        os.makedirs(os.path.dirname(self.log_file), exist_ok=True)

    def load_all(self) -> List[PaperPositionRecord]:
        positions = []
        if not os.path.exists(self.log_file):
            return positions
        with open(self.log_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        data = json.loads(line)
                        positions.append(PaperPositionRecord(**data))
                    except Exception:
                        pass
        return positions

    def save_all(self, positions: List[PaperPositionRecord]):
        # Hash zincirini yeniden oluşturarak kaydet
        current_prev_hash = GENESIS_HASH
        for p in positions:
            p.prev_record_hash = current_prev_hash
            p.record_hash = compute_record_hash(current_prev_hash, p.model_dump())
            current_prev_hash = p.record_hash

        with open(self.log_file, "w", encoding="utf-8") as f:
            for p in positions:
                f.write(json.dumps(p.model_dump(), ensure_ascii=False) + "\n")

    def get_active_position(self, ticker: str) -> Optional[PaperPositionRecord]:
        for p in self.load_all():
            if p.ticker.upper() == ticker.upper() and p.status == "DEVAM EDİYOR":
                return p
        return None

    def open_position(
        self,
        ticker: str,
        price: float,
        signal_version: int,
        stop: Optional[float] = None,
        target: Optional[float] = None,
        target_horizon: str = "2–6 ay",
        benchmark_price: Optional[float] = None,
        as_of: Optional[str] = None,
        is_demo: bool = False,
        signal_origin: str = "paper",
        data_confidence: str = "VALID"
    ) -> PaperPositionRecord:
        now_iso = as_of or datetime.now(timezone.utc).isoformat()
        pos_id = f"PAPER-{ticker.upper()}-{int(time.time()*1000)}"
        
        # Dinamik maliyet ve benchmark çözümleme
        cost_cfg = resolve_cost_model(ticker)
        bm_sym, bm_name = resolve_benchmark(ticker)
        
        # Varsayılan benchmark fiyatları
        if benchmark_price is None:
            if bm_sym == "XU100":
                bm_price = 10000.0
            elif bm_sym == "BTC":
                bm_price = 65000.0
            elif bm_sym == "XAU":
                bm_price = 2650.0
            else:
                bm_price = 500.0
        else:
            bm_price = benchmark_price

        comm_rate = cost_cfg["commission_rate"]
        slip_rate = cost_cfg["slippage_rate"]
        initial_cost_pct = (comm_rate + slip_rate) * 100

        pos = PaperPositionRecord(
            position_id=pos_id,
            ticker=ticker.upper(),
            signal_version=signal_version,
            status="DEVAM EDİYOR",
            entry_price=price,
            entry_time=now_iso,
            current_price=price,
            stop=stop,
            target=target,
            target_horizon=target_horizon,
            commission_rate=comm_rate,
            slippage_rate=slip_rate,
            benchmark_symbol=bm_sym,
            benchmark_name=bm_name,
            benchmark_entry_price=bm_price,
            benchmark_current_price=bm_price,
            unrealized_return_pct=-round(initial_cost_pct, 3),
            max_drawdown_pct=0.0,
            is_demo=is_demo,
            signal_origin=signal_origin,
            data_confidence=data_confidence
        )
        
        positions = self.load_all()
        positions.append(pos)
        self.save_all(positions)
        return pos

    def update_price(
        self,
        ticker: str,
        current_price: float,
        current_benchmark_price: Optional[float] = None
    ) -> Optional[PaperPositionRecord]:
        positions = self.load_all()
        updated = None
        for p in positions:
            if p.ticker.upper() == ticker.upper() and p.status == "DEVAM EDİYOR":
                p.current_price = current_price
                if current_benchmark_price is not None:
                    p.benchmark_current_price = current_benchmark_price

                # Brüt getiri
                gross_ret = ((current_price - p.entry_price) / p.entry_price) * 100
                # Net getiri (Giriş/çıkış komisyon + kayma)
                total_cost_pct = (p.commission_rate * 2 + p.slippage_rate * 2) * 100
                p.unrealized_return_pct = round(gross_ret - total_cost_pct, 2)

                # Benchmark getiri ve alfa
                if p.benchmark_entry_price > 0 and p.benchmark_current_price > 0:
                    bm_ret = ((p.benchmark_current_price - p.benchmark_entry_price) / p.benchmark_entry_price) * 100
                    p.benchmark_return_pct = round(bm_ret, 2)
                    p.alpha_pct = round(p.unrealized_return_pct - bm_ret, 2)

                # Drawdown takibi
                if gross_ret < 0:
                    p.max_drawdown_pct = min(p.max_drawdown_pct, round(gross_ret, 2))

                # R-multiple hesabı
                if p.stop and p.entry_price != p.stop:
                    risk_dist = abs(p.entry_price - p.stop)
                    p.r_multiple = round((current_price - p.entry_price) / risk_dist, 2)

                updated = p
                break

        if updated:
            self.save_all(positions)
        return updated

    def close_position(
        self,
        ticker: str,
        exit_price: float,
        reason: str,
        exit_time: Optional[str] = None,
        exit_benchmark_price: Optional[float] = None
    ) -> Optional[PaperPositionRecord]:
        positions = self.load_all()
        closed = None
        for p in positions:
            if p.ticker.upper() == ticker.upper() and p.status == "DEVAM EDİYOR":
                now_iso = exit_time or datetime.now(timezone.utc).isoformat()
                p.exit_price = exit_price
                p.exit_time = now_iso
                p.exit_reason = reason
                p.status = "GERÇEKLEŞEN"

                if exit_benchmark_price is not None:
                    p.benchmark_current_price = exit_benchmark_price

                # Brüt ve Net gerçekleşen getiri
                gross_ret = ((exit_price - p.entry_price) / p.entry_price) * 100
                total_cost_pct = (p.commission_rate * 2 + p.slippage_rate * 2) * 100
                p.realized_return_pct = round(gross_ret - total_cost_pct, 2)

                # Benchmark getiri ve Alfa
                if p.benchmark_entry_price > 0 and p.benchmark_current_price > 0:
                    bm_ret = ((p.benchmark_current_price - p.benchmark_entry_price) / p.benchmark_entry_price) * 100
                    p.benchmark_return_pct = round(bm_ret, 2)
                    p.alpha_pct = round(p.realized_return_pct - bm_ret, 2)

                # Nihai R-Multiple
                if p.stop and p.entry_price != p.stop:
                    risk_dist = abs(p.entry_price - p.stop)
                    p.r_multiple = round((exit_price - p.entry_price) / risk_dist, 2)

                closed = p
                break

        if closed:
            self.save_all(positions)
        return closed

    def verify_chain_integrity(self) -> Dict[str, Any]:
        """Paper pozisyon kayıtlarının hash zinciri bütünlüğünü denetler."""
        positions = self.load_all()
        if not positions:
            return {"valid": True, "count": 0, "message": "Pozisyon zinciri boş"}

        expected_prev_hash = GENESIS_HASH
        for idx, pos in enumerate(positions):
            if pos.prev_record_hash != expected_prev_hash:
                return {
                    "valid": False,
                    "tampered_index": idx,
                    "position_id": pos.position_id,
                    "error": f"Pozisyon {idx} prev_record_hash uyuşmazlığı"
                }

            calculated = compute_record_hash(expected_prev_hash, pos.model_dump())
            if pos.record_hash != calculated:
                return {
                    "valid": False,
                    "tampered_index": idx,
                    "position_id": pos.position_id,
                    "error": f"Pozisyon {idx} tahrif edilmiş!"
                }

            expected_prev_hash = pos.record_hash

        return {"valid": True, "count": len(positions), "message": "Pozisyon zinciri eksiksiz doğrulandı."}

    def get_live_performance_summary(self, exclude_demo: bool = True) -> Dict[str, Any]:
        all_positions = self.load_all()
        positions = [p for p in all_positions if not p.is_demo] if exclude_demo else all_positions
        demo_count = len(all_positions) - len(positions)

        closed = [p for p in positions if p.status == "GERÇEKLEŞEN"]
        active = [p for p in positions if p.status == "DEVAM EDİYOR"]

        realized_returns = [p.realized_return_pct for p in closed if p.realized_return_pct is not None]
        wins = [r for r in realized_returns if r > 0]
        losses = [r for r in realized_returns if r < 0]

        win_rate = round((len(wins) / len(realized_returns)) * 100, 1) if realized_returns else 0.0
        gross_win = sum(wins)
        gross_loss = abs(sum(losses))
        profit_factor = round(gross_win / gross_loss, 2) if gross_loss > 0 else (round(gross_win, 2) if gross_win > 0 else 1.0)
        avg_return = round(sum(realized_returns) / len(realized_returns), 2) if realized_returns else 0.0
        worst_dd = min([p.max_drawdown_pct for p in positions] or [0.0])
        r_multiples = [p.r_multiple for p in closed]
        avg_r = round(sum(r_multiples) / len(r_multiples), 2) if r_multiples else 0.0

        # Benchmark bazlı ortalama alfa
        alphas = [p.alpha_pct for p in closed]
        avg_alpha = round(sum(alphas) / len(alphas), 2) if alphas else 0.0

        return {
            "total_positions": len(positions),
            "demo_positions_filtered_out": demo_count,
            "active_positions_count": len(active),
            "closed_positions_count": len(closed),
            "win_rate_pct": win_rate,
            "profit_factor": profit_factor,
            "avg_return_pct": avg_return,
            "avg_alpha_pct": avg_alpha,
            "max_drawdown_pct": worst_dd,
            "avg_r_multiple": avg_r,
            "model_version": "v4.2-core",
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "real_trading_blocked": True,
            "labels": ["PAPER", "GERÇEKLEŞEN", "DEVAM EDİYOR", "VERİ BEKLENİYOR"]
        }


# ════════════════════════════════════════════════════════════════════
# 6. KARAR DEĞERLENDİRME VE CANLI PİYASA MOTORU
# ════════════════════════════════════════════════════════════════════

class ShovelDecisionChainEngine:
    """
    Quant & Harness kararlarını zaman içinde sürümleyen, 
    karar geçmişini kriptografik hash zinciriyle koruyan,
    canlı piyasa beslemeleriyle (live market feed) pozisyonları güncelleyen ana motor.
    """
    def __init__(self, journal: Optional[DecisionJournal] = None, portfolio: Optional[PaperPortfolio] = None):
        self.journal = journal or DecisionJournal()
        self.portfolio = portfolio or PaperPortfolio()

    def process_evaluation(
        self,
        ticker: str,
        new_decision: str,
        current_price: float,
        snapshot_id: str,
        data_as_of: str,
        quant_scores: Optional[Dict[str, Any]] = None,
        risk_status: str = "Normal",
        stop_level: Optional[float] = None,
        target_level: Optional[float] = None,
        target_horizon: str = "2–6 ay",
        benchmark_price: Optional[float] = None,
        explanation_text: str = "",
        data_confidence: Optional[str] = None,
        has_fundamental_data: bool = True,
        has_risk_data: bool = True,
        sources_conflict: bool = False,
        sector: str = "TECHNOLOGY",
        is_demo: bool = False,
        signal_origin: str = "paper"
    ) -> Tuple[Optional[DecisionVersionRecord], str]:
        """Yeni bir snapshot ile varlığı değerlendirir."""
        active_pos = self.portfolio.get_active_position(ticker)
        stop_target_needed = (new_decision in ["AL"] or (new_decision == "SAT" and not active_pos))
        has_stop_target_effective = bool(stop_level and target_level) if stop_target_needed else True

        # 1. Veri Güveni Değerlendirmesi (Bölüm 1)
        computed_conf, conf_msg, conf_meta = DataConfidenceEvaluator.evaluate(
            has_price=(current_price > 0),
            has_snapshot=bool(snapshot_id),
            has_risk_data=has_risk_data,
            has_fundamental_data=has_fundamental_data,
            has_stop_target=has_stop_target_effective,
            sources_conflict=sources_conflict
        )
        final_conf = data_confidence or computed_conf

        # Kural: INSUFFICIENT_DATA durumunda yeni karar üretilmez!
        if final_conf == "INSUFFICIENT_DATA" or not conf_meta["allow_decision"]:
            return None, "INSUFFICIENT_DATA"

        # Kural: PARTIAL_CONFIDENCE durumunda risk/stop eksikse yeni AL/SAT pozisyonu açılamaz, İZLE'ye çekilir
        if final_conf == "PARTIAL_CONFIDENCE" and not conf_meta.get("allow_new_position", True):
            if new_decision in ["AL"] or (new_decision == "SAT" and not active_pos):
                new_decision = "İZLE"

        # 2. Altman Z & Beneish M Sektör ve TFRS Kalibrasyon Kısıtı (Bölüm 5)
        is_bist = ticker.upper().endswith(".IS") or ticker.upper() in BIST_SYMBOLS
        altman_beneish = AltmanBeneishEvaluator.evaluate_inclusion(
            sector=sector,
            is_bist=is_bist,
            has_sufficient_inputs=has_fundamental_data
        )

        latest = self.journal.get_latest_decision(ticker)
        scores = quant_scores or {}

        # Kural: Aynı snapshot ile tekrar karar üretilmez
        if latest and latest.snapshot_id == snapshot_id:
            return None, "SKIPPED_DUPLICATE_SNAPSHOT"

        previous_decision = latest.new_decision if latest else None
        current_version = (latest.decision_version + 1) if latest else 1

        is_changed = (previous_decision != new_decision)

        # Değişim nedenleri çıkarımı
        change_reasons = []
        if is_changed:
            if previous_decision:
                prev_mom = latest.quant_scores.get("momentum", 50) if latest else 50
                cur_mom = scores.get("momentum", 50)
                if cur_mom < prev_mom:
                    change_reasons.append("Momentum zayıfladı")
                elif cur_mom > prev_mom:
                    change_reasons.append("Momentum güçlendi")

                if risk_status in ["Yüksek", "Kritik"] or scores.get("risk", 30) > 60:
                    change_reasons.append("Risk skoru yükseldi")

                if new_decision == "SAT" and previous_decision in ["AL", "TUT"]:
                    change_reasons.append("Stop mesafesi daraldı ve risk sınırı aşıldı")
                elif new_decision == "TUT" and previous_decision == "AL":
                    change_reasons.append("Mevcut kâr koruma eşiğine ulaşıldı, elde tutma moduna geçildi")
                elif new_decision == "AL" and previous_decision in ["SAT", "İZLE"]:
                    change_reasons.append("Değerleme iskontosu ve asimetrik getiri koridoru onaylandı")
            else:
                change_reasons.append("İlk sistem analizi ve başlangıç değerlendirmesi")

        # Rejim, Kuyruk Riski ve Robust İstatistik
        regime_eval = _global_regime_engine.evaluate_regime(
            trend_direction="positive" if scores.get("momentum", 50) >= 50 else "negative",
            ewma_vol=float(scores.get("ewma_volatility_pct", 25.0)) / 100.0 if scores.get("ewma_volatility_pct") else 0.25,
            yield_curve_spread=0.15,
            rate_change_3m=0.0,
            market_breadth=0.60,
            historical_vol_percentile=50.0,
            data_as_of=data_as_of
        )
        sim_ret = [-0.01, 0.005, -0.015, 0.02, -0.008, 0.012]
        tail_risk_eval = TailRiskEngine.calculate_tail_risk(sim_ret, data_as_of=data_as_of)
        _, robust_meta = RobustStats.robust_zscore([float(scores.get("composite", 60.0)), 50.0, 70.0])

        dec_id = f"DEC-{ticker.upper()}-v{current_version}-{hashlib.md5(f'{ticker}{snapshot_id}{new_decision}'.encode()).hexdigest()[:8].upper()}"

        record = DecisionVersionRecord(
            decision_id=dec_id,
            ticker=ticker.upper(),
            decision_version=current_version,
            previous_decision=previous_decision,
            new_decision=new_decision,
            changed_at=datetime.now(timezone.utc).isoformat(),
            change_reason=change_reasons,
            snapshot_id=snapshot_id,
            model_version="v4.2-core",
            data_as_of=data_as_of,
            decision_source="quant_harness",
            price=current_price,
            quant_scores=scores,
            risk_status=risk_status,
            data_confidence=final_conf,
            ui_confidence_label=CONFIDENCE_UI_LABELS.get(final_conf, "Tam veri"),
            is_technical_only=conf_meta.get("is_technical_only", False),
            is_demo=is_demo,
            signal_origin=signal_origin,
            altman_status=altman_beneish["altman_status"],
            beneish_status=altman_beneish["beneish_status"],
            exclusion_reason=altman_beneish["exclusion_reason"],
            regime_state=regime_eval["regime"],
            tail_risk_metrics=tail_risk_eval,
            robust_scaling=robust_meta,
            explanation=explanation_text or (f"Karar {previous_decision}'tan {new_decision}'a değişti: {', '.join(change_reasons)}" if is_changed else f"{new_decision} kararı teyit edildi.")
        )

        # Karar günlüğüne kaydet (Yalnızca karar değiştiyse veya ilk kararsa)
        if is_changed or not latest:
            self.journal.append_decision(record)

        # ── PAPER PORTFÖY GEÇİŞ KURALLARI ───────────────────────────────
        active_pos = self.portfolio.get_active_position(ticker)

        if previous_decision == "AL" and new_decision == "TUT":
            if active_pos:
                self.portfolio.update_price(ticker, current_price, benchmark_price)

        elif previous_decision == "TUT" and new_decision == "SAT":
            if active_pos:
                self.portfolio.close_position(
                    ticker, current_price,
                    reason="Karar TUT'tan SAT'a değişti (Risk/Momentum)",
                    exit_time=record.changed_at,
                    exit_benchmark_price=benchmark_price
                )

        elif previous_decision == "AL" and new_decision == "SAT":
            if active_pos:
                self.portfolio.close_position(
                    ticker, current_price,
                    reason="Karar AL'dan SAT'a değişti",
                    exit_time=record.changed_at,
                    exit_benchmark_price=benchmark_price
                )

        elif previous_decision == "SAT" and new_decision == "AL":
            self.portfolio.open_position(
                ticker=ticker,
                price=current_price,
                signal_version=current_version,
                stop=stop_level,
                target=target_level,
                target_horizon=target_horizon,
                benchmark_price=benchmark_price,
                as_of=record.changed_at,
                is_demo=is_demo,
                signal_origin=signal_origin,
                data_confidence=final_conf
            )

        elif previous_decision == "TUT" and new_decision == "AL":
            if not active_pos:
                self.portfolio.open_position(
                    ticker=ticker,
                    price=current_price,
                    signal_version=current_version,
                    stop=stop_level,
                    target=target_level,
                    target_horizon=target_horizon,
                    benchmark_price=benchmark_price,
                    as_of=record.changed_at,
                    is_demo=is_demo,
                    signal_origin=signal_origin,
                    data_confidence=final_conf
                )
            else:
                self.portfolio.update_price(ticker, current_price, benchmark_price)

        elif not previous_decision and new_decision == "AL":
            self.portfolio.open_position(
                ticker=ticker,
                price=current_price,
                signal_version=current_version,
                stop=stop_level,
                target=target_level,
                target_horizon=target_horizon,
                benchmark_price=benchmark_price,
                as_of=record.changed_at,
                is_demo=is_demo,
                signal_origin=signal_origin,
                data_confidence=final_conf
            )

        elif active_pos:
            self.portfolio.update_price(ticker, current_price, benchmark_price)

        return record, "SUCCESS"

    def sync_with_live_market_data(
        self,
        market_quotes: Dict[str, Dict[str, Any]],
        benchmark_quotes: Optional[Dict[str, float]] = None
    ) -> Dict[str, Any]:
        """
        Canlı piyasa veri beslemesi (real market quotes) ile paper portföyü senkronize eder.
        
        Args:
            market_quotes: { "NVDA": {"price": 121.5, "time": "..."}, "THYAO": {"price": 312.0} }
            benchmark_quotes: { "SPY": 512.0, "XU100": 9850.0, "BTC": 64500.0, "XAU": 2660.0 }
        """
        bm_quotes = benchmark_quotes or {}
        active_positions = [p for p in self.portfolio.load_all() if p.status == "DEVAM EDİYOR"]

        updated_count = 0
        triggered_stops = []
        triggered_targets = []

        for p in active_positions:
            t = p.ticker.upper()
            quote_data = market_quotes.get(t)
            if not quote_data:
                continue

            current_price = float(quote_data.get("price", quote_data.get("close", 0.0)))
            if current_price <= 0:
                continue

            # Doğru benchmark cari fiyatı
            bm_sym = p.benchmark_symbol
            bm_cur_price = bm_quotes.get(bm_sym, p.benchmark_current_price)

            # 1. Stop-Loss Kontrolü (Long pozisyon için price <= stop)
            if p.stop is not None and current_price <= p.stop:
                self.portfolio.close_position(
                    ticker=t,
                    exit_price=current_price,
                    reason=f"Stop-Loss Tetiklendi (Piyasa Fiyatı: ${current_price:.2f} <= Stop: ${p.stop:.2f})",
                    exit_time=datetime.now(timezone.utc).isoformat(),
                    exit_benchmark_price=bm_cur_price
                )
                triggered_stops.append({"ticker": t, "exit_price": current_price, "stop": p.stop})
                continue

            # 2. Kâr Al / Hedef Kontrolü (Long pozisyon için price >= target)
            if p.target is not None and current_price >= p.target:
                self.portfolio.close_position(
                    ticker=t,
                    exit_price=current_price,
                    reason=f"Kâr Al Hedefi Gerçekleşti (Piyasa Fiyatı: ${current_price:.2f} >= Hedef: ${p.target:.2f})",
                    exit_time=datetime.now(timezone.utc).isoformat(),
                    exit_benchmark_price=bm_cur_price
                )
                triggered_targets.append({"ticker": t, "exit_price": current_price, "target": p.target})
                continue

            # 3. Canlı Mark-to-Market Fiyat Güncellemesi
            self.portfolio.update_price(
                ticker=t,
                current_price=current_price,
                current_benchmark_price=bm_cur_price
            )
            updated_count += 1

        return {
            "sync_time": datetime.now(timezone.utc).isoformat(),
            "active_positions_checked": len(active_positions),
            "updated_positions_count": updated_count,
            "triggered_stops": triggered_stops,
            "triggered_targets": triggered_targets,
            "status": "LIVE_FEED_SYNCED"
        }


# Global Tekil Nesne
shovel_decision_engine = ShovelDecisionChainEngine()

if __name__ == "__main__":
    print("Shovel Decision Chain & Live Paper Engine v1.1.0 Ready.")
    print("REAL_TRADING_ENABLED:", REAL_TRADING_ENABLED)
    print("Decision Chain Integrity:", shovel_decision_engine.journal.verify_chain_integrity())
    print("Paper Portfolio Integrity:", shovel_decision_engine.portfolio.verify_chain_integrity())
