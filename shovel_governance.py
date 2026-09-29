# -*- coding: utf-8 -*-
"""
shovel_governance.py — Shovel Yönetişim, Veri Güvenilirliği ve Güvenlik Katmanı

KAPSAM:
1. Veri Güven Durumları (VALID, PARTIAL_CONFIDENCE, INSUFFICIENT_DATA) ve eşik kuralları.
2. Kaynaklar Arası Uyum (Cross-Source Alignment): Öncelik hiyerarşisi, tolerans kontrolü (CF_SYNC_FAIL) ve async requestId takibi.
3. AI_GUARD Şema Koruması: Yasaklı alan filtresi, AI_GUARD_BLOCKED loglama ve template fallback.
4. Batch Hesaplama Takvimi: Modellerin çalışma frekansları, zaman damgası ve bayat veri koruması.
5. Altman Z ve Beneish M Sınırı: Sektör uyumsuzluğu, TFRS kalibrasyonu ve ana skordan hariç tutma (MF_CORE).
6. Demo ve Gerçek Sinyal İzolasyonu: is_demo = True kayıtlarının performans metriklerinden kesin ayrımı.
7. NautilusTrader Sınırı: Yalnızca araştırma/backtest modülü, Jev/Harness kararına müdahale edemez.
"""

from __future__ import annotations

import os
import sys
import json
import time
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple, Literal
from pydantic import BaseModel, Field, ConfigDict, ValidationError

# UTF-8 stdout
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

VAULT_DIR = r"c:\Users\Cihan\Desktop\ikinci-beyin"
JOURNAL_DIR = os.path.join(VAULT_DIR, "journal")
GOVERNANCE_LOG_FILE = os.path.join(JOURNAL_DIR, "governance_events.jsonl")


# ════════════════════════════════════════════════════════════════════
# 1. VERİ GÜVEN DURUMLARI (DATA CONFIDENCE STATES)
# ════════════════════════════════════════════════════════════════════

DataConfidenceState = Literal["VALID", "PARTIAL_CONFIDENCE", "INSUFFICIENT_DATA"]

CONFIDENCE_UI_LABELS = {
    "VALID": "Tam veri",
    "PARTIAL_CONFIDENCE": "Teknik veriye dayalı (Düşük güven)",
    "INSUFFICIENT_DATA": "Karar üretilemedi (Yetersiz veri)"
}

class DataConfidenceEvaluator:
    """
    Veri sağlığı ve güvenilirlik durumunu değerlendiren deterministik motor:
    - VALID: Fiyat, snapshot ve temel veriler güncel ve eksiksiz.
    - PARTIAL_CONFIDENCE: Fiyat güncel ancak temel veri eksik veya risk verisi sınırlı.
    - INSUFFICIENT_DATA: Fiyat eksik, snapshot bozuk veya kaynaklar çelişkili.
    """
    @staticmethod
    def evaluate(
        has_price: bool,
        has_snapshot: bool,
        has_risk_data: bool,
        has_fundamental_data: bool,
        has_stop_target: bool,
        sources_conflict: bool = False
    ) -> Tuple[DataConfidenceState, str, Dict[str, Any]]:
        # 1. Çelişki veya kritik eksiklik kontrolü -> INSUFFICIENT_DATA
        if sources_conflict:
            return "INSUFFICIENT_DATA", "Kaynaklar arasında çelişki tespit edildi (Tolerans aşıldı)", {
                "allow_decision": False,
                "allow_new_position": False,
                "is_technical_only": False,
                "ui_label": CONFIDENCE_UI_LABELS["INSUFFICIENT_DATA"]
            }

        if not has_price or not has_snapshot:
            return "INSUFFICIENT_DATA", "Fiyat veya piyasa snapshot verisi eksik", {
                "allow_decision": False,
                "allow_new_position": False,
                "is_technical_only": False,
                "ui_label": CONFIDENCE_UI_LABELS["INSUFFICIENT_DATA"]
            }

        # 2. Risk verisi eksikse veya Stop/Hedef hesaplanamıyorsa -> PARTIAL_CONFIDENCE (AL/SAT önerilemez, İZLE)
        if not has_risk_data or not has_stop_target:
            return "PARTIAL_CONFIDENCE", "Risk veya Stop/Hedef hesaplanamadı; yeni AL/SAT önerilemez, İZLE moduna alındı", {
                "allow_decision": True,
                "allow_new_position": False,  # Yeni pozisyon yasak
                "forced_decision": "İZLE",
                "is_technical_only": True,
                "ui_label": "Düşük güven (Risk/Stop eksik)"
            }

        # 3. Fiyat güncel ama temel veri (bilanço/FCF) eksikse -> PARTIAL_CONFIDENCE (Teknik Karar)
        if not has_fundamental_data:
            return "PARTIAL_CONFIDENCE", "Bilanço verisi eksik; karar yalnızca teknik verilere dayalıdır", {
                "allow_decision": True,
                "allow_new_position": True,
                "is_technical_only": True,
                "ui_label": CONFIDENCE_UI_LABELS["PARTIAL_CONFIDENCE"]
            }

        # 4. Tam ve eksiksiz -> VALID
        return "VALID", "Tüm kritik ve temel veriler güncel ve uyumlu", {
            "allow_decision": True,
            "allow_new_position": True,
            "is_technical_only": False,
            "ui_label": CONFIDENCE_UI_LABELS["VALID"]
        }


# ════════════════════════════════════════════════════════════════════
# 2. KAYNAKLAR ARASI UYUM VE TOLERANS (CROSS-SOURCE ALIGNMENT)
# ════════════════════════════════════════════════════════════════════

SOURCE_PRIORITY = {
    "live_exchange": 1,     # Canlı borsa / exchange feed (En yüksek)
    "official_api": 2,      # Resmi kurum / API (TCMB, Fed, SEC, KAP)
    "market_api": 3,        # Güvenilir piyasa API'si (Yahoo, OpenBB)
    "cache": 4              # Yerel önbellek (En düşük)
}

TOLERANCE_MAP = {
    "crypto": 0.0010,       # %0.10
    "us_equities": 0.0025,  # %0.25
    "bist_equities": 0.0050,# %0.50
    "commodities": 0.0025,  # %0.25
    "default": 0.0025
}

class SourceQuoteRecord(BaseModel):
    source: str
    symbol: str
    price: float
    as_of: str
    fetched_at: str
    freshness_seconds: float
    priority: int
    snapshot_id: str

class CrossSourceAlignmentEngine:
    """
    Farklı kaynaklardan gelen fiyatları öncelik sırasına göre hizalar.
    Tolerans aşılırsa CF_SYNC_FAIL tetikler ve karar üretimini durdurur.
    """
    @staticmethod
    def resolve_tolerance(asset_class: str) -> float:
        return TOLERANCE_MAP.get(asset_class.lower(), TOLERANCE_MAP["default"])

    @staticmethod
    def align_sources(
        symbol: str,
        quotes: List[SourceQuoteRecord],
        asset_class: str = "us_equities"
    ) -> Tuple[bool, Optional[SourceQuoteRecord], str]:
        if not quotes:
            return False, None, "Hiçbir kaynaktan kotasyon alınamadı"

        # Önceliğe göre sırala (priority: 1 en yüksek)
        sorted_quotes = sorted(quotes, key=lambda q: q.priority)
        best_quote = sorted_quotes[0]

        if len(sorted_quotes) == 1:
            return True, best_quote, "Tek kaynak doğrulandı"

        tolerance = CrossSourceAlignmentEngine.resolve_tolerance(asset_class)
        primary_price = best_quote.price

        # İkincil kaynaklarla farkı kıyasla
        for other in sorted_quotes[1:]:
            if other.price <= 0:
                continue
            diff_pct = abs(primary_price - other.price) / primary_price
            if diff_pct > tolerance:
                msg = (f"CF_SYNC_FAIL: {symbol} için {best_quote.source} (${primary_price:.4f}) ile "
                       f"{other.source} (${other.price:.4f}) arasındaki fark (%{diff_pct*100:.3f}), "
                       f"izin verilen toleransı (%{tolerance*100:.2f}) aştı!")
                return False, None, msg

        return True, best_quote, "Kaynaklar arası uyum onaylandı"


class AsyncRequestTracker:
    """
    Asenkron ağ yanıtlarının birbirini ezmesini (race condition)
    artan requestId mekanizmasıyla engelleyen takipçi.
    """
    def __init__(self):
        self._latest_request_ids: Dict[str, int] = {}

    def get_next_request_id(self, symbol: str) -> int:
        sym = symbol.upper()
        cur = self._latest_request_ids.get(sym, 0) + 1
        self._latest_request_ids[sym] = cur
        return cur

    def is_response_valid(self, symbol: str, request_id: int) -> bool:
        sym = symbol.upper()
        latest = self._latest_request_ids.get(sym, 0)
        return request_id >= latest


# ════════════════════════════════════════════════════════════════════
# 3. AI_GUARD ŞEMA KORUMASI (STRICT OUTPUT FIREWALL)
# ════════════════════════════════════════════════════════════════════

FORBIDDEN_LLM_OUTPUT_KEYS = {
    "decision", "price", "score", "stop", "target", "return",
    "benchmark_value", "position_size"
}

class AIGuardPermittedOutput(BaseModel):
    """
    LLM'in üretmesine İZİN VERİLEN tek geçerli şema.
    extra='forbid' kuralı ile yasaklı veya fazladan hiçbir alan kabul edilmez.
    """
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(description="1-2 cümlelik sade, anlaşılır Türkçe açıklama.")
    reasons: List[str] = Field(default_factory=list, description="Kararı destekleyen gerekçeler.")
    risks: List[str] = Field(default_factory=list, description="En fazla 3 adet risk maddesi.")
    data_warning: str = Field(default="", description="Varsa eksik veri uyarısı.")
    plain_explanation: str = Field(default="", description="Yatırımcıya yönelik sade dille özet.")

class AIGuardFirewall:
    """
    LLM yanıtlarını sıkı JSON şemasıyla süzen ve yasaklı alanları (fiyat, karar, skor vb.)
    anında tespit edip engelleyen güvenlik kalkanı.
    """
    @staticmethod
    def validate_and_filter(
        raw_output: Dict[str, Any],
        fallback_summary: str = "Deterministik sistem özeti uygulandı."
    ) -> Tuple[bool, AIGuardPermittedOutput, Optional[str]]:
        # 1. Yasaklı alan kontrolü
        violated_keys = [k for k in raw_output.keys() if k.lower().strip() in FORBIDDEN_LLM_OUTPUT_KEYS]
        if violated_keys:
            error_msg = f"AI_GUARD_BLOCKED: LLM yetki dışı alan(lar) üretti: {violated_keys}"
            AIGuardFirewall.log_security_event("AI_GUARD_BLOCKED", {
                "violated_keys": violated_keys,
                "raw_keys": list(raw_output.keys())
            })
            # Template fallback
            fallback = AIGuardPermittedOutput(
                summary=fallback_summary,
                reasons=["Quant modeli ve Harness kuralları korundu."],
                risks=["LLM güvenlik kalkanı devreye girdi."],
                data_warning="AI_GUARD_BLOCKED: Yasaklı alan girişimi engellendi.",
                plain_explanation=fallback_summary
            )
            return False, fallback, error_msg

        # 2. Pydantic şema doğrulaması
        try:
            validated = AIGuardPermittedOutput(**raw_output)
            return True, validated, None
        except ValidationError as e:
            error_msg = f"AI_GUARD_SCHEMA_INVALID: {str(e)}"
            AIGuardFirewall.log_security_event("AI_GUARD_SCHEMA_INVALID", {"error": str(e)})
            fallback = AIGuardPermittedOutput(
                summary=fallback_summary,
                reasons=[],
                risks=[],
                data_warning="Şema doğrulama hatası nedeniyle şablon açıklaması kullanıldı.",
                plain_explanation=fallback_summary
            )
            return False, fallback, error_msg

    @staticmethod
    def log_security_event(event_type: str, details: Dict[str, Any]):
        os.makedirs(os.path.dirname(GOVERNANCE_LOG_FILE), exist_ok=True)
        rec = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "details": details
        }
        with open(GOVERNANCE_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# ════════════════════════════════════════════════════════════════════
# 4. BATCH HESAPLAMA TAKVİMİ VE FRESHNESS YÖNETİMİ
# ════════════════════════════════════════════════════════════════════

BATCH_SCHEDULE = {
    "ewma_volatility": {"interval": "daily", "ttl_seconds": 86400 * 1.5, "desc": "EWMA Volatilite"},
    "beta_momentum_var": {"interval": "daily", "ttl_seconds": 86400 * 1.5, "desc": "Beta, Momentum, VaR/CVaR"},
    "garch": {"interval": "daily_if_sufficient", "ttl_seconds": 86400 * 2.0, "desc": "GARCH İleri Analiz"},
    "dcf_wacc": {"interval": "on_earnings_or_weekly", "ttl_seconds": 86400 * 7.5, "desc": "DCF / WACC Değerleme"},
    "fama_french": {"interval": "monthly_or_factor_update", "ttl_seconds": 86400 * 35.0, "desc": "Fama-French 3/5 Faktör"},
    "monte_carlo_dcf": {"interval": "weekly_or_assumption_change", "ttl_seconds": 86400 * 7.5, "desc": "Monte Carlo DCF Dağılımı"},
    "walk_forward_backtest": {"interval": "nightly_batch", "ttl_seconds": 86400 * 1.5, "desc": "Walk-Forward Gece Backtesti"}
}

class BatchCalculationResult(BaseModel):
    model_name: str
    calculated_at: str
    data_as_of: str
    model_version: str
    formula_version: str
    payload: Dict[str, Any]

class BatchScheduleManager:
    """
    Ağır modellerin çalışma takvimini denetler.
    Tarihi geçmiş batch sonuçlarını 'eski batch sonucu' olarak işaretler ve yeni karar üretimini engeller.
    """
    @staticmethod
    def is_result_fresh(calc_result: BatchCalculationResult) -> Tuple[bool, str]:
        cfg = BATCH_SCHEDULE.get(calc_result.model_name)
        if not cfg:
            return True, "Özel takvim tanımlı değil"

        try:
            calc_dt = datetime.fromisoformat(calc_result.calculated_at.replace("Z", "+00:00"))
            age_sec = (datetime.now(timezone.utc) - calc_dt).total_seconds()
            ttl = cfg["ttl_seconds"]
            if age_sec > ttl:
                return False, f"Eski batch sonucu (Yaş: {age_sec/86400:.1f} gün, TTL: {ttl/86400:.1f} gün). Yeni karar üretilemez."
            return True, "Batch sonucu taze"
        except Exception as e:
            return False, f"Tarih ayrıştırma hatası: {e}"


# ════════════════════════════════════════════════════════════════════
# 5. ALTMAN VE BENEISH KISITI (MF_CORE GÜVENLİK SINIRI)
# ════════════════════════════════════════════════════════════════════

INCOMPATIBLE_SECTORS_ALTMAN = {
    "FINANCE", "BANKING", "INSURANCE", "REAL_ESTATE", "REIT", "HOLDING"
}

INCOMPATIBLE_SECTORS_BENEISH = {
    "FINANCE", "BANKING", "INSURANCE", "REAL_ESTATE", "REIT", "ASSET_LIGHT_TECH"
}

class AltmanBeneishEvaluator:
    """
    Altman Z-Score ve Beneish M-Score modellerini ana kompozit skora (MF_CORE)
    otomatik dahil etmez. Yalnızca belirli kriterleri sağlayan sektörlerde
    bilgi/uyarı amacıyla çalıştırır; aksi takdirde ana skordan hariç tutar.
    """
    @staticmethod
    def evaluate_inclusion(
        sector: str,
        is_bist: bool,
        has_sufficient_inputs: bool
    ) -> Dict[str, Any]:
        sec = sector.upper().strip()

        # Altman Değerlendirmesi
        altman_status = "included"
        altman_reasons = []

        if not has_sufficient_inputs:
            altman_status = "excluded"
            altman_reasons.append("Gerekli bilanço girdileri eksik")
        elif sec in INCOMPATIBLE_SECTORS_ALTMAN:
            altman_status = "warning_only"
            altman_reasons.append(f"Altman Z-Score {sec} sektör yapısıyla uyumsuzdur (Yalnızca bilgi amaçlı)")
        elif is_bist:
            altman_status = "warning_only"
            altman_reasons.append("BIST TFRS enflasyon muhasebesi kalibrasyonu belirsiz (Uyarı amaçlı)")

        # Beneish Değerlendirmesi
        beneish_status = "included"
        beneish_reasons = []

        if not has_sufficient_inputs:
            beneish_status = "excluded"
            beneish_reasons.append("Gerekli 8 oran girdisi eksik")
        elif sec in INCOMPATIBLE_SECTORS_BENEISH:
            beneish_status = "warning_only"
            beneish_reasons.append(f"Beneish M-Score {sec} bilanço dinamikleriyle uyumsuzdur")
        elif is_bist:
            beneish_status = "warning_only"
            beneish_reasons.append("TFRS dipnotları otomatik M-Score için kalibre edilmemiş")

        return {
            "altman_status": altman_status,
            "altman_reasons": altman_reasons,
            "beneish_status": beneish_status,
            "beneish_reasons": beneish_reasons,
            "affects_composite_score": (altman_status == "included" and beneish_status == "included"),
            "exclusion_reason": "; ".join(altman_reasons + beneish_reasons) if (altman_status != "included" or beneish_status != "included") else ""
        }


# ════════════════════════════════════════════════════════════════════
# 6. DEMO VE GERÇEK SİNYAL İZOLASYONU (DEMO FILTER)
# ════════════════════════════════════════════════════════════════════

SignalOriginType = Literal["demo", "paper", "live_observation"]

class SignalDemoFilter:
    """
    Demo sinyalleri (is_demo: True) canlı performans, win rate, profit factor,
    alfa, Sharpe ve Brier skorlarından kesin olarak izole eder.
    """
    @staticmethod
    def filter_signals(signals: List[Dict[str, Any]], exclude_demo: bool = True) -> List[Dict[str, Any]]:
        if not exclude_demo:
            return signals
        return [s for s in signals if s.get("is_demo") is not True]

    @staticmethod
    def calculate_forward_metrics(signals: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Yalnızca gerçek paper veya canlı gözlem sinyallerini hesaplar.
        is_demo: True kayıtları kesinlikle dahil edilmez.
        """
        valid_signals = [s for s in signals if s.get("is_demo") is not True]
        demo_count = len(signals) - len(valid_signals)

        closed = [s for s in valid_signals if s.get("status") == "GERÇEKLEŞEN"]
        returns = [s.get("realized_return_pct") for s in closed if s.get("realized_return_pct") is not None]
        
        wins = [r for r in returns if r > 0]
        losses = [r for r in returns if r < 0]

        win_rate = round((len(wins) / len(returns)) * 100, 1) if returns else 0.0
        gross_win = sum(wins)
        gross_loss = abs(sum(losses))
        pf = round(gross_win / gross_loss, 2) if gross_loss > 0 else (round(gross_win, 2) if gross_win > 0 else 1.0)
        avg_ret = round(sum(returns) / len(returns), 2) if returns else 0.0

        return {
            "total_signals": len(valid_signals),
            "demo_signals_filtered_out": demo_count,
            "closed_count": len(closed),
            "win_rate_pct": win_rate,
            "profit_factor": pf,
            "avg_return_pct": avg_ret,
            "demo_contamination_safe": True
        }


# ════════════════════════════════════════════════════════════════════
# 7. NAUTILUSTRADER MİMARİ SINIRI
# ════════════════════════════════════════════════════════════════════

class NautilusTraderBoundaryGuard:
    """
    NautilusTrader'ın Shovel karar zinciriyle ilişkisini kesin olarak sınırlar:
    1. NautilusTrader yalnızca 'Ayrı Araştırma / Backtest Modülü'dür.
    2. Jev / Harness kararlarını veya Shovel sinyallerini değiştiremez.
    3. Çıktıları Signal Log'a yalnızca 'research_result' etiketiyle işlenebilir.
    4. Gerçek piyasaya emir gönderemez.
    """
    @staticmethod
    def assert_research_only(adapter_result: Dict[str, Any]) -> Dict[str, Any]:
        # Karar alanlarını temizle / izole et
        is_research = adapter_result.get("is_research_only", True)
        real_trading = adapter_result.get("real_trading_enabled", False)

        if real_trading:
            raise PermissionError("NAUTILUS_BOUNDARY_BREACH: NautilusTrader gerçek işlem yapamaz!")

        return {
            "module": "NautilusTrader Research Adapter",
            "is_research_only": True,
            "real_trading_enabled": False,
            "can_alter_shovel_decision": False,
            "shovel_harness_veto_respected": True,
            "status": "RESEARCH_LOGGED_ONLY",
            "backtest_metrics": adapter_result.get("metrics", {})
        }


if __name__ == "__main__":
    print("Shovel Governance & Data Reliability Layer v1.2.0 initialized.")
    # Quick self check
    conf, reason, meta = DataConfidenceEvaluator.evaluate(
        has_price=True, has_snapshot=True, has_risk_data=True,
        has_fundamental_data=False, has_stop_target=True
    )
    print(f"Data Confidence Check: {conf} ({reason})")
    alt = AltmanBeneishEvaluator.evaluate_inclusion("BANKING", is_bist=True, has_sufficient_inputs=True)
    print(f"Altman/Beneish Gate for Banking: {alt['altman_status']} - {alt['exclusion_reason']}")
