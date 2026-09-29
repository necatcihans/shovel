# -*- coding: utf-8 -*-
"""
shovel_quant_interpreter.py — Shovel Quant Yorumlama ve Sözel Çeviri Katmanı

KAPSAM:
1. Standart Metrik Yorum Şeması (Ham Değer, Birim, Karşılaştırma, Sözel Etiket, Sade Anlam, Güven, Eşik Sürümü)
2. Deterministik Eşik Tabloları (Sharpe, CVaR %95, Altman Z, Beta, MoS, RSI)
3. 3 Kademeli Karşılaştırma Katmanı (Tarihsel, Sektör, Benchmark - Eksikse dürüstçe bildir)
4. Belirsizlik ve Koridor Yorumu (Dar, Orta, Geniş aralık, Conformal ve Monte Carlo)
5. Çoklu Metrik Sentez Şablon Motoru (LLM'siz deterministik kural tabanlı)
6. İleri Analiz Paneli Statik "Bu ne anlama gelir?" Sözlüğü
7. Yerel LLM Hava Boşluğu Sınırları (numbers_changed: false, decision_changed: false)
"""

from __future__ import annotations

import os
import sys
import re
import json
import time
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple, Literal, Union
from pydantic import BaseModel, Field, ConfigDict

# UTF-8 stdout
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

VAULT_DIR = r"c:\Users\Cihan\Desktop\ikinci-beyin"
CONFIG_DIR = os.path.join(VAULT_DIR, "config")
JOURNAL_DIR = os.path.join(VAULT_DIR, "journal")
INTERPRETER_LOG_FILE = os.path.join(JOURNAL_DIR, "quant_interpreter_events.jsonl")
COMMENT_THRESHOLDS_PATH = os.path.join(CONFIG_DIR, "comment_thresholds.json")

os.makedirs(CONFIG_DIR, exist_ok=True)
os.makedirs(JOURNAL_DIR, exist_ok=True)

THRESHOLD_VERSION = "v2.0"


class CommentThresholdManager:
    """Varlık sınıfına özel eşikleri config dosyasından okuyan yönetici (Bölüm 1)."""
    _cached_config: Optional[Dict[str, Any]] = None

    @classmethod
    def load_config(cls) -> Dict[str, Any]:
        if cls._cached_config is not None:
            return cls._cached_config
        if os.path.exists(COMMENT_THRESHOLDS_PATH):
            try:
                with open(COMMENT_THRESHOLDS_PATH, "r", encoding="utf-8") as f:
                    cls._cached_config = json.load(f)
                    return cls._cached_config
            except Exception:
                pass
        return {
            "config_version": "v2.0",
            "last_updated": "2026-09-28T12:00:00Z",
            "classes": {}
        }

    @classmethod
    def get_config_version(cls) -> str:
        return cls.load_config().get("config_version", "v2.0")

    @classmethod
    def get_thresholds_for_class(cls, asset_class: str) -> Dict[str, Any]:
        cfg = cls.load_config()
        classes = cfg.get("classes", {})
        ac = (asset_class or "equity").lower().strip()
        # Takma ad ve alt sınıf eşleştirmeleri
        if ac in ["us_equity", "bist_equity", "stock", "equity"]:
            return classes.get("equity", {})
        elif ac in ["crypto", "cryptocurrency"]:
            return classes.get("crypto", {})
        elif ac in ["commodity", "commodities"]:
            return classes.get("commodity", {})
        elif ac in ["fx", "forex", "currency"]:
            return classes.get("fx", {})
        elif ac in ["bond", "bonds", "rate"]:
            return classes.get("bond", {})
        elif ac in ["index", "etf"]:
            return classes.get("index", classes.get("equity", {}))
        elif ac in ["macro"]:
            return classes.get("macro", {})
        return classes.get(ac, classes.get("equity", {}))

    @classmethod
    def log_threshold_event(cls, action: str, details: Dict[str, Any]):
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "details": details,
            "version": cls.get_config_version()
        }
        try:
            with open(INTERPRETER_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        except Exception:
            pass


class AnalysisSnapshot(BaseModel):
    """Tek snapshot parametresi şeması (Bölüm 2)."""
    model_config = ConfigDict(extra="allow")

    symbol: str
    asset_class: str = "equity"
    current_decision: str = "İZLE"
    previous_decision: Optional[str] = None
    decision_version: int = 0
    snapshot_id: str = "SNAP-INIT"
    price: float = 0.0
    momentum: float = 0.0
    trend: float = 0.0
    volatility: float = 0.0
    volatility_percentile: float = 0.50
    valuation: float = 0.0
    quality: float = 0.50
    risk: float = 0.0
    benchmark_difference: float = 0.0
    data_quality: str = "FULL"  # "FULL", "PARTIAL", "STALE", "INVALID"
    freshness: str = "fresh"    # "fresh", "stale"
    macro_regime: str = "neutral"
    coverage: Optional[float] = None
    trigger_context: Dict[str, Any] = Field(default_factory=dict)


class DynamicCommentResult(BaseModel):
    """Dinamik yorum üretim çıktısı şeması (Bölüm 4)."""
    model_config = ConfigDict(extra="allow")

    text: str
    short_text: str
    source_metrics: List[str]
    triggered_rules: List[str]
    priority_path: List[str]
    threshold_version: str
    snapshot_id: str
    llm_payload: Dict[str, Any]
    explanation_breakdown: Dict[str, Any]


# ════════════════════════════════════════════════════════════════════
# 1. METRİK YORUM ŞEMASI
# ════════════════════════════════════════════════════════════════════

class MetricInterpretation(BaseModel):
    model_config = ConfigDict(extra="allow")

    metric: str
    value: Any
    unit: str = ""
    comparison: str = "Karşılaştırma verisi bulunamadı."
    label: str
    plain_meaning: str
    confidence: Literal["high", "medium", "low"] = "medium"
    data_as_of: str
    threshold_version: str = THRESHOLD_VERSION


class MultiMetricSynthesis(BaseModel):
    model_config = ConfigDict(extra="allow")

    text: str
    triggered_rules: List[str]
    source_metrics: List[str]
    rule_version: str = THRESHOLD_VERSION


# ════════════════════════════════════════════════════════════════════
# 2. STATİK SÖZLÜK: “BU NE ANLAMA GELİR?” (LLM'E ÇAĞRI GEREKMEZ)
# ════════════════════════════════════════════════════════════════════

STATIC_EXPLANATION_DICTIONARY = {
    "sharpe": "Aldığın risk birimine karşılık elde edilen getiriyi ölçer. Yüksek değer, aynı riskte daha iyi getiri anlamına gelir.",
    "cvar": "Belirli kötü senaryolarda (%95 güven aralığında) beklenen ortalama zararı ve kuyruk riskini gösterir.",
    "beta": "Hissenin piyasaya (endekse) göre ne kadar sert hareket ettiğini gösterir. 1.0 piyasayla paralel demektir.",
    "mos": "Modelin hesapladığı adil değer ile borsa fiyatı arasındaki güvenlik payıdır; pozitif olması koruma sağlar.",
    "volatility": "Son fiyat hareketlerine ağırlık vererek fiyattaki dalgalanma şiddetini ölçer.",
    "altman_z": "Şirketin bilanço verilerine göre finansal sağlamlığını ve iflas riskine mesafesini ölçer.",
    "piotroski_f": "Şirketin kârlılık, kaldıraç ve operasyonel verimliliğini 0–9 puan arasında özetleyen kalite skorudur.",
    "rsi": "Fiyatın son günlerdeki yükseliş ve düşüş hızını 0–100 arasında kıyaslayarak aşırı alım/satımı gösterir."
}


# ════════════════════════════════════════════════════════════════════
# 3. METRİK EŞİK MOTORU (DETERMİNİSTİK IF/ELSE)
# ════════════════════════════════════════════════════════════════════

class QuantMetricInterpreter:
    """LLM kullanmadan kurallı eşik tabloları ve karşılaştırmalar üreten motor."""

    @staticmethod
    def interpret_sharpe(value: Optional[float], sector_avg: Optional[float] = None, as_of: str = "") -> MetricInterpretation:
        if value is None:
            return MetricInterpretation(
                metric="Sharpe Ratio",
                value="—",
                label="Veri Yok",
                plain_meaning="Yeterli getiri geçmişi bulunamadığı için Sharpe hesaplanamadı.",
                confidence="low",
                data_as_of=as_of or datetime.now(timezone.utc).strftime("%Y-%m-%d")
            )

        val = float(value)
        if val < 0.0:
            label = "Risk alınmasına rağmen getiri zayıf"
            meaning = "Yatırım riski alınmasına rağmen getiri negatif veya risksiz faizin altında kaldı."
        elif val < 0.5:
            label = "Zayıf risk-getiri dengesi"
            meaning = "Risk birimi başına elde edilen getiri potansiyeli düşüktür."
        elif val < 1.0:
            label = "Makul risk-getiri dengesi"
            meaning = "Risk ile getiri dengesi kabul edilebilir piyasa normundadır."
        elif val <= 2.0:
            label = "İyi risk-getiri dengesi"
            meaning = "Alınan risk başına getirisi ortalamanın üzerinde ve verimlidir."
        else:
            label = "Çok güçlü; sürdürülebilirliği ayrıca doğrula"
            meaning = "Aşırı yüksek getiri verimliliği; dönemsel anomali veya sürdürülebilirlik kontrol edilmelidir."

        comp = f"Sektör ortalaması: {sector_avg:.2f}" if sector_avg is not None else "Karşılaştırma verisi bulunamadı."

        return MetricInterpretation(
            metric="Sharpe Ratio",
            value=round(val, 2),
            unit="",
            comparison=comp,
            label=label,
            plain_meaning=meaning,
            confidence="high" if sector_avg is not None else "medium",
            data_as_of=as_of or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        )

    @staticmethod
    def interpret_cvar(
        cvar_pct: Optional[float],
        portfolio_size: float = 10000.0,
        currency: str = "USD",
        as_of: str = ""
    ) -> MetricInterpretation:
        if cvar_pct is None:
            return MetricInterpretation(
                metric="CVaR %95",
                value="—",
                label="Veri Yok",
                plain_meaning="Kuyruk riski hesaplanamadı.",
                confidence="low",
                data_as_of=as_of or datetime.now(timezone.utc).strftime("%Y-%m-%d")
            )

        pct = float(cvar_pct)
        loss_amount = (portfolio_size * pct) / 100.0

        if pct < 5.0:
            label = "Düşük kayıp"
        elif pct <= 10.0:
            label = "Orta kayıp"
        elif pct <= 18.0:
            label = "Yüksek kayıp"
        else:
            label = "Çok yüksek kuyruk riski"

        formatted_meaning = f"%95 senaryoda beklenen en kötü kayıp: portföyün %{pct:.1f}'i, yaklaşık {loss_amount:,.0f} {currency}."

        return MetricInterpretation(
            metric="CVaR %95",
            value=round(pct, 2),
            unit="%",
            comparison=f"Portföy büyüklüğü: {portfolio_size:,.0f} {currency}",
            label=label,
            plain_meaning=formatted_meaning,
            confidence="high",
            data_as_of=as_of or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        )

    @staticmethod
    def interpret_altman_z(
        value: Optional[float],
        sector: str = "technology",
        as_of: str = ""
    ) -> MetricInterpretation:
        sec_lower = (sector or "").lower()
        # Finans, Bankacılık ve Kripto için Altman Z standart modeli geçerli değildir
        if any(bad in sec_lower for bad in ["bank", "finan", "crypto", "insurance", "sigorta"]):
            return MetricInterpretation(
                metric="Altman Z-Score",
                value=round(value, 2) if value is not None else "—",
                unit="",
                comparison="Sektör uyumsuz (Finans/Banka/Kripto)",
                label="Deneysel / ana karara dahil değil",
                plain_meaning="Altman Z üretim ve perakende şirketleri için tasarlanmıştır; finansal yapısı farklı sektörlerde ana kararı etkilemez.",
                confidence="low",
                data_as_of=as_of or datetime.now(timezone.utc).strftime("%Y-%m-%d")
            )

        if value is None:
            return MetricInterpretation(
                metric="Altman Z-Score",
                value="—",
                label="Veri Yok",
                plain_meaning="Bilanço verisi eksik olduğu için Altman Z hesaplanamadı.",
                confidence="low",
                data_as_of=as_of or datetime.now(timezone.utc).strftime("%Y-%m-%d")
            )

        val = float(value)
        if val > 2.99:
            label = "Finansal yapı güvenli bölgede"
            meaning = "Şirketin sermaye ve borç dengesi sağlam; kısa/orta vadeli finansal sıkıntı riski düşüktür."
        elif val >= 1.81:
            label = "Gri bölge, dikkat gerekli"
            meaning = "Finansal kaldıraç ve likidite dengesi orta seviyede; nakit akışları yakından izlenmelidir."
        else:
            label = "Finansal sıkıntı riski yüksek"
            meaning = "Şirketin borçluluk ve kârlılık yapısı baskı altındadır; iflas veya temerrüt riski mevcuttur."

        return MetricInterpretation(
            metric="Altman Z-Score",
            value=round(val, 2),
            unit="",
            comparison="Güvenli Eşik: > 2.99",
            label=label,
            plain_meaning=meaning,
            confidence="high",
            data_as_of=as_of or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        )

    @staticmethod
    def interpret_beta(value: Optional[float], benchmark: str = "SPY", as_of: str = "") -> MetricInterpretation:
        if value is None:
            return MetricInterpretation(
                metric="CAPM Beta",
                value="—",
                label="Veri Yok",
                plain_meaning="Piyasa korelasyonu hesaplanamadı.",
                confidence="low",
                data_as_of=as_of or datetime.now(timezone.utc).strftime("%Y-%m-%d")
            )

        val = float(value)
        if val < 0.8:
            label = "Piyasadan daha az oynak"
            meaning = f"Hisse {benchmark} endeksine göre daha defansif ve dalgalanmalara karşı daha dayanıklıdır."
        elif val <= 1.2:
            label = "Piyasaya benzer hareket"
            meaning = f"Hisse {benchmark} endeksiyle uyumlu bir dalgalanma gösterir."
        else:
            label = "Piyasadan daha oynak"
            meaning = f"Piyasa hareketlerine karşı aşırı duyarlıdır; endeks düşerken veya çıkarken daha sert tepki verir."

        return MetricInterpretation(
            metric="CAPM Beta",
            value=round(val, 2),
            unit="",
            comparison=f"Benchmark: {benchmark} (Beta: 1.0)",
            label=label,
            plain_meaning=meaning,
            confidence="high",
            data_as_of=as_of or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        )

    @staticmethod
    def interpret_mos(value_pct: Optional[float], as_of: str = "") -> MetricInterpretation:
        if value_pct is None:
            return MetricInterpretation(
                metric="Güvenlik Marjı (MoS)",
                value="—",
                label="Veri Yok",
                plain_meaning="İçsel değerleme modeli çalıştırılamadı.",
                confidence="low",
                data_as_of=as_of or datetime.now(timezone.utc).strftime("%Y-%m-%d")
            )

        val = float(value_pct)
        if val > 15.0:
            label = "Değerleme açısından güvenlik payı var"
            meaning = f"Fiyat içsel değerin yaklaşık %{val:.1f} altında; olası piyasa düşüşlerine karşı koruma sağlar."
        elif val > 0.0:
            label = "Sınırlı güvenlik payı"
            meaning = f"Fiyat içsel değere göre %{val:.1f} iskontolu; güvenlik marjı mütevazıdır."
        elif val >= -5.0:
            label = "Fiyat adil değere yakın"
            meaning = "Fiyat modelin belirlediği adil değerle neredeyse birebir dengede."
        else:
            label = "Fiyat model değerinin üzerinde"
            meaning = f"Piyasa fiyatı adil değerin yaklaşık %{abs(val):.1f} üzerinde işlem görüyor (primli)."

        return MetricInterpretation(
            metric="Güvenlik Marjı (MoS)",
            value=round(val, 1),
            unit="%",
            comparison="Graham Güvenlik Eşiği: > %15.0",
            label=label,
            plain_meaning=meaning,
            confidence="high",
            data_as_of=as_of or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        )

    @staticmethod
    def interpret_rsi(value: Optional[float], as_of: str = "") -> MetricInterpretation:
        if value is None:
            return MetricInterpretation(
                metric="RSI (14)",
                value="—",
                label="Veri Yok",
                plain_meaning="Momentum verisi eksik.",
                confidence="low",
                data_as_of=as_of or datetime.now(timezone.utc).strftime("%Y-%m-%d")
            )

        val = float(value)
        if val < 30.0:
            label = "Aşırı satım bölgesi"
            meaning = "Fiyat kısa vadede sert düştü; tepki alımı ihtimali var ancak trend ve hacimle birlikte izlenmelidir."
        elif val <= 70.0:
            label = "Nötr bölge"
            meaning = "Momentum dengeli bir aralıkta seyrediyor."
        else:
            label = "Aşırı alım bölgesi"
            meaning = "Kısa vadede hızlı yükseliş yaşandı; kâr realizasyonu riski artmış olabilir."

        return MetricInterpretation(
            metric="RSI (14)",
            value=round(val, 1),
            unit="",
            comparison="Nötr Bant: 30–70 (RSI tek başına AL/SAT sinyali üretmez)",
            label=label,
            plain_meaning=meaning,
            confidence="high",
            data_as_of=as_of or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        )


# ════════════════════════════════════════════════════════════════════
# 4. BELİRSİZLİK VE TAHMİN KORİDORU YORUMU
# ════════════════════════════════════════════════════════════════════

class UncertaintyInterpreter:
    """Nokta tahminleri tek başına sunmaz; koridor genişliği ve güven aralığını açıklar."""

    @staticmethod
    def interpret_corridor(
        point_estimate: float,
        low_bound: float,
        high_bound: float,
        currency: str = "TL",
        target_coverage: float = 0.90,
        observed_coverage: float = 0.88,
        calib_window: str = "60 gün"
    ) -> Dict[str, Any]:
        spread = high_bound - low_bound
        spread_pct = (spread / point_estimate) * 100.0 if point_estimate > 0 else 0.0

        if spread_pct < 15.0:
            uncertainty_label = "Belirsizlik düşük"
            corridor_type = "Dar aralık"
            confidence = "Yüksek"
            comment = "Tahmin koridoru dar ve model parametreleri tutarlı."
        elif spread_pct <= 30.0:
            uncertainty_label = "Belirsizlik orta"
            corridor_type = "Orta aralık"
            confidence = "Orta"
            comment = "Piyasa koşulları ve volatilite orta düzeyde belirsizlik içeriyor."
        else:
            uncertainty_label = "Belirsizlik yüksek"
            corridor_type = "Geniş aralık"
            confidence = "Düşük"
            comment = "Tahmin aralığı geniş; yüksek volatilite veya sınırlı veri belirsizliği artırıyor."

        text = f"Değerleme aralığı: {low_bound:,.1f}–{high_bound:,.1f} {currency} | Güven: {confidence} | Yorum: {comment}"

        return {
            "text": text,
            "corridor_type": corridor_type,
            "uncertainty_label": uncertainty_label,
            "confidence": confidence,
            "spread_pct": round(spread_pct, 1),
            "target_coverage": target_coverage,
            "observed_coverage": observed_coverage,
            "calibration_window": calib_window,
            "data_as_of": datetime.now(timezone.utc).strftime("%Y-%m-%d")
        }


# ════════════════════════════════════════════════════════════════════
# 5. ÇOKLU METRİK SENTEZ ŞABLON MOTORU (LLM'SİZ DETERMINİSTİK)
# ════════════════════════════════════════════════════════════════════

class MultiMetricSynthesizer:
    """Metriklerin kombinasyonundan deterministik kural tabanlı üst düzey özet cümleler üretir."""

    @staticmethod
    def synthesize(
        mos_pct: Optional[float],
        sharpe: Optional[float],
        altman_zone: str,  # "safe", "grey", "distress", "incompatible"
        cvar_pct: Optional[float],
        volatility_high: bool,
        data_quality: str = "FULL"  # "FULL", "PARTIAL", "STALE"
    ) -> MultiMetricSynthesis:
        triggered_rules = []
        source_metrics = []
        sentences = []

        # Kural 5: Veri kalitesi denetimi
        if data_quality != "FULL":
            triggered_rules.append("DATA_QUALITY_WARNING")
            sentences.append("Bu sonuç eksik veya eski veri nedeniyle düşük güvenle değerlendirilmelidir.")

        # Kural 1: Değerleme cazip + Sharpe iyi + Altman güvenli
        if mos_pct is not None and mos_pct > 0 and sharpe is not None and sharpe > 1.0 and altman_zone == "safe":
            triggered_rules.extend(["MOS_POSITIVE", "SHARPE_GOOD", "ALTMAN_SAFE"])
            source_metrics.extend(["mos", "sharpe", "altman_z"])
            sentences.append("Değerleme cazip, risk-getiri dengesi iyi ve finansal yapı sağlam.")

        # Kural 2: Değerleme pahalı + Sharpe zayıf
        elif mos_pct is not None and mos_pct < 0 and sharpe is not None and sharpe < 0.5:
            triggered_rules.extend(["MOS_NEGATIVE", "SHARPE_WEAK"])
            source_metrics.extend(["mos", "sharpe"])
            sentences.append("Değerleme pahalı ve risk-getiri dengesi zayıf; dikkat gerekli.")

        # Kural 3: Piyasa güçlü ama finansal yapı batık (Tuzak)
        elif sharpe is not None and sharpe > 1.0 and altman_zone == "distress":
            triggered_rules.extend(["SHARPE_GOOD", "ALTMAN_DISTRESS"])
            source_metrics.extend(["sharpe", "altman_z"])
            sentences.append("Piyasa performansı güçlü görünse de finansal yapı önemli risk taşıyor.")

        # Kural 4: CVaR yüksek + Volatilite yüksek
        if cvar_pct is not None and cvar_pct > 12.0 and volatility_high:
            triggered_rules.extend(["CVAR_HIGH", "VOLATILITY_HIGH"])
            source_metrics.extend(["cvar", "volatility"])
            sentences.append("Getiri potansiyeli bulunsa da olası kayıp ve fiyat dalgalanması yüksek.")

        if not sentences:
            sentences.append("Göstergeler dengeli; belirgin bir uç risk veya aşırı değerleme sapması bulunmuyor.")
            triggered_rules.append("NEUTRAL_DEFAULT")

        combined_text = " ".join(sentences)

        record = MultiMetricSynthesis(
            text=combined_text,
            triggered_rules=list(set(triggered_rules)),
            source_metrics=list(set(source_metrics)),
            rule_version=THRESHOLD_VERSION
        )

        # Loglama
        try:
            with open(INTERPRETER_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(record.model_dump_json() + "\n")
        except Exception:
            pass

        return record


# ════════════════════════════════════════════════════════════════════
# 6. YEREL LLM HAVA BOŞLUĞU SINIRI VE KORUMA (AIR-GAP GUARDRAIL)
# ════════════════════════════════════════════════════════════════════

class LocalLLMExplainerGuard:
    """
    Yerel Ollama / Qwen modeline yalnızca sözel etiketler gönderilir.
    Model yeni sayı üretemez, eşik değiştiremez, kararı değiştiremez (Bölüm 7).
    """

    @staticmethod
    def build_llm_payload(
        labels: List[str],
        risks: List[str],
        data_warning: str = "",
        previous_decision: str = "",
        current_decision: str = ""
    ) -> Dict[str, Any]:
        return {
            "labels": labels,
            "risks": risks,
            "data_warning": data_warning,
            "previous_decision": previous_decision,
            "current_decision": current_decision
        }

    @staticmethod
    def sanitize_llm_output(
        raw_output: str,
        fallback_summary: str,
        fallback_risks: List[str],
        expected_decision: str = ""
    ) -> Dict[str, Any]:
        """LLM çıktısını doğrular ve sayı/karar tahrifatını engeller."""
        summary = fallback_summary
        risks = fallback_risks
        data_warning = ""

        try:
            # JSON bloğu ayıkla
            match = re.search(r"\{.*\}", raw_output, re.DOTALL)
            if match:
                parsed = json.loads(match.group(0))
                # 1. Karar tahrifatı kontrolü
                llm_dec = parsed.get("decision") or parsed.get("current_decision")
                if llm_dec and expected_decision and str(llm_dec).upper() != str(expected_decision).upper():
                    return {
                        "summary": fallback_summary,
                        "risks": fallback_risks,
                        "data_warning": "LLM yetkisiz karar değiştirme denemesi tespit edildi; deterministik şablona dönüldü.",
                        "numbers_changed": False,
                        "decision_changed": False
                    }

                # 2. Sayı üretme girişimi kontrolü
                summary_cand = parsed.get("summary", "")
                if summary_cand:
                    # Yeni rakamlar içeriyor mu kontrolü
                    digits = re.findall(r"\b\d+(?:[\.,]\d+)?%?\b", summary_cand)
                    if digits:
                        return {
                            "summary": fallback_summary,
                            "risks": fallback_risks,
                            "data_warning": "LLM yetkisiz sayısal değer üretme denemesi tespit edildi; deterministik şablona dönüldü.",
                            "numbers_changed": False,
                            "decision_changed": False
                        }
                    summary = summary_cand

                risks = parsed.get("risks", fallback_risks)
                data_warning = parsed.get("data_warning", "")
        except Exception:
            pass

        return {
            "summary": summary,
            "risks": risks,
            "data_warning": data_warning,
            "numbers_changed": False,
            "decision_changed": False
        }


# ════════════════════════════════════════════════════════════════════
# 6B. KURAL ÖNCELİK AĞACI İLE DİNAMİK YORUM MOTORU (BÖLÜM 2, 3, 4, 5)
# ════════════════════════════════════════════════════════════════════

def generate_dynamic_comment(
    analysis_snapshot: Union[Dict[str, Any], AnalysisSnapshot]
) -> Dict[str, Any]:
    """
    Tek bir analysisSnapshot parametresi alarak 6 kademeli kural öncelik ağacıyla
    deterministik dinamik yorum üretir (Bölüm 2 ve 3).
    """
    if isinstance(analysis_snapshot, dict):
        snap = AnalysisSnapshot(**analysis_snapshot)
    else:
        snap = analysis_snapshot

    cfg_ver = CommentThresholdManager.get_config_version()
    th = CommentThresholdManager.get_thresholds_for_class(snap.asset_class)

    triggered_rules: List[str] = []
    priority_path: List[str] = []
    source_metrics: List[str] = []
    sentences: List[str] = []

    # ──────────────────────────────────────────────────────────────────
    # ADIM 1: RİSK VE VERİ GEÇERLİLİĞİ (VETO KONTROLÜ)
    # ──────────────────────────────────────────────────────────────────
    is_risk_veto = (
        snap.trigger_context.get("risk_veto") is True or
        snap.risk >= 80.0 or
        snap.current_decision.upper() in ["UYGUN DEĞİL", "RİSKLİ", "VETO", "HALT"] or
        snap.data_quality.upper() == "INVALID" or
        (snap.freshness.lower() == "stale" and snap.trigger_context.get("critical_price_stale") is True) or
        snap.trigger_context.get("snapshot_mismatch") is True or
        snap.trigger_context.get("source_conflict") is True
    )

    if is_risk_veto:
        veto_text = "Risk veya veri doğrulama sorunu nedeniyle yeni pozisyon önerilmiyor."
        triggered_rules.append("RISK_OR_DATA_INVALID_VETO")
        priority_path.append("1_RISK_AND_DATA_VALIDITY")
        source_metrics.extend(["risk", "data_quality", "freshness"])

        res = {
            "text": veto_text,
            "short_text": veto_text,
            "source_metrics": list(set(source_metrics)),
            "triggered_rules": triggered_rules,
            "priority_path": priority_path,
            "threshold_version": cfg_ver,
            "snapshot_id": snap.snapshot_id,
            "llm_payload": {
                "labels": triggered_rules,
                "risks": ["Yüksek risk / veri doğrulama engeli"],
                "data_warning": "Risk veya veri doğrulama sorunu mevcut.",
                "previous_decision": snap.previous_decision or "—",
                "current_decision": snap.current_decision
            },
            "explanation_breakdown": {
                "triggered_rules": triggered_rules,
                "metrics_used": {
                    "risk": snap.risk,
                    "data_quality": snap.data_quality,
                    "freshness": snap.freshness
                },
                "snapshot_info": {
                    "snapshot_id": snap.snapshot_id,
                    "symbol": snap.symbol,
                    "source": snap.trigger_context.get("source", "canonical_resolver"),
                    "as_of": snap.trigger_context.get("as_of", datetime.now(timezone.utc).isoformat())
                }
            }
        }
        try:
            with open(INTERPRETER_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(res, ensure_ascii=False) + "\n")
        except Exception:
            pass
        return res

    # ──────────────────────────────────────────────────────────────────
    # ADIM 2: VERİ KALİTESİ DENETİMİ
    # ──────────────────────────────────────────────────────────────────
    data_warning_str = ""
    if snap.data_quality.upper() in ["PARTIAL", "STALE"] or snap.freshness.lower() == "stale":
        data_warning_str = "Değerlendirme eksik veya gecikmeli veri nedeniyle düşük güvenle yapılmıştır."
        sentences.append(data_warning_str)
        triggered_rules.append("DATA_QUALITY_PARTIAL_OR_STALE")
        priority_path.append("2_DATA_QUALITY")
        source_metrics.extend(["data_quality", "freshness"])

    # ──────────────────────────────────────────────────────────────────
    # ADIM 3: KARAR DEĞİŞİMİ
    # ──────────────────────────────────────────────────────────────────
    prev_d = (snap.previous_decision or "").upper().strip()
    curr_d = (snap.current_decision or "").upper().strip()

    if prev_d and curr_d and prev_d != curr_d:
        if prev_d == "AL" and curr_d in ["TUT", "İZLE", "BEKLE"]:
            sentences.append("Önceki değerlendirmeye göre görünüm zayıfladı.")
            triggered_rules.append("DECISION_CHANGE_AL_TUT")
            priority_path.append("3_DECISION_CHANGE")
            source_metrics.extend(["previous_decision", "current_decision"])
        elif prev_d in ["TUT", "İZLE", "BEKLE"] and curr_d == "AL":
            sentences.append("Önceki değerlendirmeye göre görünüm güçlendi.")
            triggered_rules.append("DECISION_CHANGE_TUT_AL")
            priority_path.append("3_DECISION_CHANGE")
            source_metrics.extend(["previous_decision", "current_decision"])
        elif prev_d in ["AL", "TUT"] and curr_d in ["SAT", "UYGUN DEĞİL", "RİSKLİ"]:
            sentences.append("Risk ve görünüm değiştiği için karar aşağı yönlü güncellendi.")
            triggered_rules.append("DECISION_CHANGE_AL_SAT")
            priority_path.append("3_DECISION_CHANGE")
            source_metrics.extend(["previous_decision", "current_decision"])
        elif prev_d in ["SAT", "UYGUN DEĞİL", "RİSKLİ"] and curr_d in ["AL", "TUT"]:
            sentences.append("Teknik görünüm önceki değerlendirmeye göre iyileşti.")
            triggered_rules.append("DECISION_CHANGE_SAT_AL")
            priority_path.append("3_DECISION_CHANGE")
            source_metrics.extend(["previous_decision", "current_decision"])

    # ──────────────────────────────────────────────────────────────────
    # ADIM 4: MOMENTUM VE VOLATİLİTE
    # ──────────────────────────────────────────────────────────────────
    mom_th = th.get("momentum", {})
    vol_th = th.get("volatility_percentile", {})
    trend_th = th.get("trend_strength", {})

    mom_strong_pos = mom_th.get("strong_positive", 0.60)
    mom_pos = mom_th.get("positive", 0.15)
    mom_neg = mom_th.get("negative", -0.15)
    vol_low = vol_th.get("low", 0.35)
    vol_high = vol_th.get("high", 0.70)
    trend_weak = trend_th.get("weak", 0.20)

    # 1. Güçlü momentum + düşük volatilite
    if snap.momentum >= mom_strong_pos and snap.volatility_percentile <= vol_low:
        sentences.append("Momentum güçlü ve dalgalanma kontrollü; trend istikrarlı ilerliyor.")
        triggered_rules.append("MOMENTUM_STRONG_VOL_LOW")
        priority_path.append("4_MOMENTUM_AND_VOLATILITY")
        source_metrics.extend(["momentum", "volatility_percentile"])
    # 2. Güçlü momentum + yüksek volatilite
    elif snap.momentum >= mom_strong_pos and snap.volatility_percentile >= vol_high:
        sentences.append("Momentum olumlu, ancak fiyat dalgalanması yüksek. Bu nedenle görünüm pozitif olsa da risk seviyesi orta.")
        triggered_rules.append("MOMENTUM_POSITIVE_VOLATILITY_HIGH")
        priority_path.append("4_MOMENTUM_AND_VOLATILITY")
        source_metrics.extend(["momentum", "volatility_percentile"])
    # 3. Zayıf momentum + yükselen volatilite
    elif snap.momentum <= mom_neg and snap.volatility_percentile >= vol_high:
        sentences.append("Momentum zayıf ve dalgalanma artıyor; aşağı yönlü kırılım riski mevcut.")
        triggered_rules.append("MOMENTUM_WEAK_VOLATILITY_HIGH")
        priority_path.append("4_MOMENTUM_AND_VOLATILITY")
        source_metrics.extend(["momentum", "volatility_percentile"])
    # 4. Nötr momentum + düşük trend gücü
    elif abs(snap.momentum) < 0.20 and snap.trend <= trend_weak:
        sentences.append("Momentum nötr ve trend gücü zayıf; yatay bant hareketi korunuyor.")
        triggered_rules.append("MOMENTUM_NEUTRAL_TREND_WEAK")
        priority_path.append("4_MOMENTUM_AND_VOLATILITY")
        source_metrics.extend(["momentum", "trend"])
    elif snap.momentum >= mom_pos:
        sentences.append("Momentum pozitif ve alıcı ilgisi sürüyor.")
        triggered_rules.append("MOMENTUM_POSITIVE")
        priority_path.append("4_MOMENTUM_AND_VOLATILITY")
        source_metrics.append("momentum")
    else:
        sentences.append("Momentum dengeli ve dalgalanma normal seviyelerde seyrediyor.")
        triggered_rules.append("MOMENTUM_BALANCED")
        priority_path.append("4_MOMENTUM_AND_VOLATILITY")
        source_metrics.extend(["momentum", "volatility_percentile"])

    # ──────────────────────────────────────────────────────────────────
    # ADIM 5: DEĞERLEME VE KALİTE
    # ──────────────────────────────────────────────────────────────────
    val_th = th.get("valuation", {})
    qual_th = th.get("quality", {})
    val_undervalued = val_th.get("undervalued", 0.10)
    val_overvalued = val_th.get("overvalued", -0.10)
    qual_high = qual_th.get("high", 0.55)
    qual_low = qual_th.get("low", 0.35)

    if snap.valuation >= val_undervalued and snap.quality >= qual_high:
        sentences.append("Değerleme iskontolu ve finansal kalite sağlam.")
        triggered_rules.append("VALUATION_POSITIVE_QUALITY_HIGH")
        priority_path.append("5_VALUATION_AND_QUALITY")
        source_metrics.extend(["valuation", "quality"])
    elif snap.valuation >= val_undervalued and snap.quality <= qual_low:
        sentences.append("Değerleme cazip görünse de kalite metrikleri temkin gerektiriyor.")
        triggered_rules.append("VALUATION_POSITIVE_QUALITY_LOW")
        priority_path.append("5_VALUATION_AND_QUALITY")
        source_metrics.extend(["valuation", "quality"])
    elif snap.valuation <= val_overvalued and snap.momentum >= mom_pos:
        sentences.append("Değerleme primli olmasına rağmen momentum güçlü seyrediyor.")
        triggered_rules.append("VALUATION_NEGATIVE_MOMENTUM_STRONG")
        priority_path.append("5_VALUATION_AND_QUALITY")
        source_metrics.extend(["valuation", "momentum"])
    elif snap.valuation <= val_overvalued and snap.momentum <= mom_neg:
        sentences.append("Değerleme pahalı ve momentum zayıf.")
        triggered_rules.append("VALUATION_NEGATIVE_MOMENTUM_WEAK")
        priority_path.append("5_VALUATION_AND_QUALITY")
        source_metrics.extend(["valuation", "momentum"])

    # ──────────────────────────────────────────────────────────────────
    # ADIM 6: BENCHMARK FARKI (YORUMUN SONUNDA)
    # ──────────────────────────────────────────────────────────────────
    if snap.benchmark_difference > 0.01:
        sentences.append("Varlık aynı dönemde benchmark’ın üzerinde performans gösterdi.")
        triggered_rules.append("BENCHMARK_OUTPERFORM")
        priority_path.append("6_BENCHMARK_DIFFERENCE")
        source_metrics.append("benchmark_difference")
    elif snap.benchmark_difference < -0.01:
        sentences.append("Varlık aynı dönemde benchmark’ın altında performans gösterdi.")
        triggered_rules.append("BENCHMARK_UNDERPERFORM")
        priority_path.append("6_BENCHMARK_DIFFERENCE")
        source_metrics.append("benchmark_difference")

    # Kısa ana ekran cümlesi (1-2 cümle)
    short_sentences = []
    if data_warning_str:
        short_sentences.append(data_warning_str)
    for s in sentences:
        if s != data_warning_str:
            short_sentences.append(s)
            if len(short_sentences) >= 2:
                break
    short_text = " ".join(short_sentences)
    full_text = " ".join(sentences)

    res = {
        "text": full_text,
        "short_text": short_text,
        "source_metrics": list(set(source_metrics)),
        "triggered_rules": triggered_rules,
        "priority_path": priority_path,
        "threshold_version": cfg_ver,
        "snapshot_id": snap.snapshot_id,
        "llm_payload": {
            "labels": triggered_rules,
            "risks": [r for r in triggered_rules if any(k in r for k in ["RISK", "WEAK", "NEGATIVE", "STALE", "VETO"])],
            "data_warning": data_warning_str,
            "previous_decision": snap.previous_decision or "—",
            "current_decision": snap.current_decision
        },
        "explanation_breakdown": {
            "triggered_rules": triggered_rules,
            "metrics_used": {
                "momentum": snap.momentum,
                "volatility_percentile": snap.volatility_percentile,
                "valuation": snap.valuation,
                "quality": snap.quality,
                "trend": snap.trend,
                "risk": snap.risk,
                "benchmark_difference": snap.benchmark_difference,
                "data_quality": snap.data_quality,
                "freshness": snap.freshness
            },
            "snapshot_info": {
                "snapshot_id": snap.snapshot_id,
                "symbol": snap.symbol,
                "source": snap.trigger_context.get("source", "canonical_resolver"),
                "as_of": snap.trigger_context.get("as_of", datetime.now(timezone.utc).isoformat())
            }
        }
    }

    try:
        with open(INTERPRETER_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(res, ensure_ascii=False) + "\n")
    except Exception:
        pass

    return res


generateDynamicComment = generate_dynamic_comment


# ════════════════════════════════════════════════════════════════════
# 7. TAM ENTEGRASYON VE ÇIKTI ÜRETECİSİ
# ════════════════════════════════════════════════════════════════════

def interpret_asset_quant_metrics(
    symbol: str,
    metrics: Dict[str, Any],
    portfolio_size: float = 10000.0,
    currency: str = "USD",
    sector: str = "technology",
    benchmark: str = "SPY",
    data_quality: str = "FULL"
) -> Dict[str, Any]:
    """
    Bir varlığın tüm quant çıktılarını standart şemayla yorumlayan ana fonksiyon.
    """
    as_of = metrics.get("as_of", datetime.now(timezone.utc).strftime("%Y-%m-%d"))

    # 1. Metrikleri yorumla
    sharpe_int = QuantMetricInterpreter.interpret_sharpe(metrics.get("sharpe"), sector_avg=metrics.get("sector_sharpe"), as_of=as_of)
    cvar_int = QuantMetricInterpreter.interpret_cvar(metrics.get("cvar_pct"), portfolio_size=portfolio_size, currency=currency, as_of=as_of)
    altman_int = QuantMetricInterpreter.interpret_altman_z(metrics.get("altman_z"), sector=sector, as_of=as_of)
    beta_int = QuantMetricInterpreter.interpret_beta(metrics.get("beta"), benchmark=benchmark, as_of=as_of)
    mos_int = QuantMetricInterpreter.interpret_mos(metrics.get("mos_pct"), as_of=as_of)
    rsi_int = QuantMetricInterpreter.interpret_rsi(metrics.get("rsi"), as_of=as_of)

    # 2. Altman Bölge Tespiti
    altman_val = metrics.get("altman_z")
    if "uyumsuz" in altman_int.comparison:
        altman_zone = "incompatible"
    elif altman_val is not None:
        altman_zone = "safe" if float(altman_val) > 2.99 else ("grey" if float(altman_val) >= 1.81 else "distress")
    else:
        altman_zone = "grey"

    # 3. Çoklu Metrik Sentezi (Deterministik Template)
    vol_high = bool(metrics.get("volatility_pct", 20.0) > 35.0)
    synthesis = MultiMetricSynthesizer.synthesize(
        mos_pct=metrics.get("mos_pct"),
        sharpe=metrics.get("sharpe"),
        altman_zone=altman_zone,
        cvar_pct=metrics.get("cvar_pct"),
        volatility_high=vol_high,
        data_quality=data_quality
    )

    # 4. Belirsizlik Koridoru
    cur_price = float(metrics.get("price", 100.0))
    low_b = float(metrics.get("target_low", cur_price * 0.90))
    high_b = float(metrics.get("target_high", cur_price * 1.15))
    uncertainty = UncertaintyInterpreter.interpret_corridor(cur_price, low_b, high_b, currency=currency)

    return {
        "symbol": symbol.upper(),
        "as_of": as_of,
        "synthesis": synthesis.model_dump(),
        "uncertainty": uncertainty,
        "interpretations": {
            "sharpe": sharpe_int.model_dump(),
            "cvar": cvar_int.model_dump(),
            "altman_z": altman_int.model_dump(),
            "beta": beta_int.model_dump(),
            "mos": mos_int.model_dump(),
            "rsi": rsi_int.model_dump()
        },
        "static_explanations": STATIC_EXPLANATION_DICTIONARY,
        "threshold_version": THRESHOLD_VERSION
    }
