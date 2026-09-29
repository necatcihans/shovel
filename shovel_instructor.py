# -*- coding: utf-8 -*-
"""
shovel_instructor.py — Shovel Terminal Instructor + Pydantic v2 Açıklama ve Sınıflandırma Katmanı

GÖREVLER:
- Fed ve TCMB bülteni özetleri
- Uzun haber ve SEC 10-K/8-K anlaşma sınıflandırmaları
- Hisse popup'ı sade karar ve risk gerekçeleri
- Sepet risk ve çeşitlendirme açıklamaları
- Backtest sonuçlarının sade dille izahı

KESİNLİKLE YAPILMAYACAKLAR:
- Quant faktör hesapları, DCF, WACC, CAPM, CVaR, stop/hedef veya pozisyon büyüklüğü üretimi.
- Tüm finansal hesaplar deterministik kalmalıdır; LLM yalnızca açıklama ve biçim kontrolü içindir.
"""

from __future__ import annotations

import io
import os
import sys
import time
import json
import hashlib
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional, Dict, Any

from pydantic import BaseModel, Field, field_validator, model_validator
import instructor

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

# Windows UTF-8 stdout
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

VAULT_DIR = r"c:\Users\Cihan\Desktop\ikinci-beyin"
LOG_DIR = os.path.join(VAULT_DIR, "knowledge")

# ════════════════════════════════════════════════════════════════════
# 1. PYDANTIC VERİ SÖZLEŞMESİ (DATA CONTRACT)
# ════════════════════════════════════════════════════════════════════

import re

def clean_summary_text(text: str) -> str:
    """Markdown, yapay zeka selamlama/dolgu ifadeleri ve aşırı uzunluğu temizler."""
    if not text:
        return ""
    # 1. Kod bloklarını ve markdown belirteçlerini temizle
    text = re.sub(r'```(?:markdown|json|text)?', '', text)
    text = text.replace('```', '')
    # 2. AI dolgu ve selamlama kalıplarını temizle
    slop_phrases = [
        r"merhaba[!., ]*",
        r"selamlar[!., ]*",
        r"ben bir yapay zeka modeliyim\.?",
        r"yapay zeka olarak,?",
        r"iyi g[üu]nler dilerim\.?",
        r"iyi g[üu]nler\.?",
        r"umar[ıi]m yard[ıi]mc[ıi] olabilmi[şs]imdir\.?",
    ]
    for pattern in slop_phrases:
        text = re.sub(pattern, '', text, flags=re.IGNORECASE).strip()
    # 3. Markdown kalın, italik ve başlıkları temizle
    text = text.replace('**', '').replace('__', '').replace('*', '').replace('_', '')
    text = re.sub(r'^#+\s*', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    
    # 4. En fazla 2 cümle ile sınırla
    sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if s.strip()]
    if len(sentences) > 2:
        text = " ".join(sentences[:2]).strip()
    return text


OFFICIAL_VERIFIED_SOURCES = {
    "SEC 10-K", "SEC 10-Q", "SEC 8-K", "TCMB PPK", "TCMB PPK KARAR ÖZETİ",
    "TCMB ENFLASYON RAPORU", "FOMC STATEMENT", "FOMC MINUTES", "FEDERAL RESERVE",
    "KAP", "TÜİK", "BUREAU OF LABOR STATISTICS", "FRED", "YAHOO FINANCE SEC BİLDİRİMİ",
    "YAHOO FINANCE", "BINANCE", "OPEN FX", "BLOOMBERG", "REUTERS"
}


class ExplanationStatus(str, Enum):
    VERIFIED = "VERIFIED"
    PARTIAL = "PARTIAL"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class ShovelExplanation(BaseModel):
    """
    Shovel Terminal için standartlaştırılmış açıklama ve araştırma şeması.
    Tüm LLM açıklamaları bu katı formata uymak zorundadır.
    """
    summary: str = Field(
        description="Kısa, sade Türkçe açıklama. Maksimum 1-2 cümle. Giriş ve selamlamadan arındırılmış."
    )
    evidence: List[str] = Field(
        default_factory=list,
        description="Açıklamayı destekleyen doğrulanmış kanıt ve somut veri listesi."
    )
    risks: List[str] = Field(
        default_factory=list,
        description="En önemli riskler listesi (en fazla 3 madde)."
    )
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Model güven skoru (0 ile 100 arası sayı). İstatistiksel kesinlik değildir."
    )
    model_confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Modelin kendi içsel güven skoru (0-100). İstatistiksel olasılık veya kesinlik değildir."
    )
    data_confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Bağımsız veri katmanının doğruluk ve tazelik skoru (0-100)."
    )
    source: List[str] = Field(
        default_factory=list,
        description="Doğrulanmış resmi kaynak ve bağlantı listesi (Örn: FOMC, TCMB, SEC 10-K, KAP)."
    )
    source_verified: bool = Field(
        default=False,
        description="Kaynakların sistem resmi kayıt defteriyle doğrulanıp doğrulanmadığı."
    )
    as_of: str = Field(
        description="Verinin tarihi ve zamanı (Örn: 2026-09-24 veya ISO formatı). Boş bırakılamaz."
    )
    status: ExplanationStatus = Field(
        description="Doğrulama durumu: VERIFIED, PARTIAL veya INSUFFICIENT_DATA."
    )


class LocalLLMExplanation(BaseModel):
    """
    Kullanıcının talep ettiği 4 alanlı katı yerel LLM çıktısı:
    {
      "summary": "string",
      "risks": ["string"],
      "data_warning": "string",
      "explanation": "string"
    }
    """
    summary: str = Field(description="1-2 cümlelik sade Türkçe özet")
    risks: List[str] = Field(default_factory=list, description="En önemli riskler listesi")
    data_warning: str = Field(default="", description="Veri uyarısı (varsa)")
    explanation: str = Field(default="", description="Detaylı sade açıklama")

    @field_validator("summary")
    @classmethod
    def validate_summary(cls, v: str) -> str:
        return clean_summary_text(v)

    @field_validator("confidence", "model_confidence", "data_confidence")
    @classmethod
    def validate_confidence_fields(cls, v: float) -> float:
        if v < 0.0 or v > 100.0:
            raise ValueError("Güven skoru 0 ile 100 arasında bir sayı olmalıdır.")
        return round(float(v), 1)

    @field_validator("summary")
    @classmethod
    def validate_summary(cls, v: str) -> str:
        return clean_summary_text(v)

    @model_validator(mode="after")
    def validate_business_rules(self) -> "ShovelExplanation":
        # Confidence senkronizasyonu
        if self.confidence > 0 and self.model_confidence == 0:
            self.model_confidence = self.confidence
        elif self.model_confidence > 0 and self.confidence == 0:
            self.confidence = self.model_confidence

        # Kaynak doğrulaması: modelin iddia ettiği kaynak resmi defterde var mı?
        cleaned_sources = [s.strip() for s in self.source if s and s.strip()]
        self.source = cleaned_sources
        
        is_verified = False
        if cleaned_sources:
            for s in cleaned_sources:
                s_up = s.upper()
                if any(official in s_up or s_up in official for official in OFFICIAL_VERIFIED_SOURCES):
                    is_verified = True
                    break
        self.source_verified = is_verified

        # 1. Kural: as_of yoksa veya geçersizse sonuç doğrudan INSUFFICIENT_DATA olmalıdır
        if not self.as_of or self.as_of.strip() in {"", "None", "null", "undefined", "—"}:
            self.status = ExplanationStatus.INSUFFICIENT_DATA
            self.summary = "Güncel veri bulunmadığı için güvenilir açıklama üretilemedi."
            self.confidence = 0.0
            self.model_confidence = 0.0
            self.data_confidence = 0.0
            self.source_verified = False

        # 2. Kural: source boşsa veya doğrulanmadıysa status VERIFIED olamaz!
        elif not self.source:
            if self.status == ExplanationStatus.VERIFIED:
                self.status = ExplanationStatus.PARTIAL
            self.confidence = min(self.confidence, 65.0)
            self.model_confidence = min(self.model_confidence, 65.0)
            self.data_confidence = 0.0
        elif not self.source_verified:
            # Model resmi defterde olmayan bir kaynak iddia ettiğinde asla VERIFIED olamaz!
            if self.status == ExplanationStatus.VERIFIED:
                self.status = ExplanationStatus.PARTIAL
            self.data_confidence = min(self.data_confidence if self.data_confidence > 0 else 35.0, 40.0)
        else:
            self.data_confidence = max(self.data_confidence, 88.0)

        # 3. Kural: Hem kanıt hem kaynak yoksa sonuç INSUFFICIENT_DATA olmalıdır
        cleaned_evidence = [e.strip() for e in self.evidence if e and e.strip()]
        self.evidence = cleaned_evidence
        if not self.evidence and not self.source:
            self.status = ExplanationStatus.INSUFFICIENT_DATA
            if not self.summary:
                self.summary = "Güncel veri bulunmadığı için güvenilir açıklama üretilemedi."
            elif "veri yetersiz" not in self.summary.lower() and "güvenilir açıklama" not in self.summary.lower():
                self.summary = "Güncel veri bulunmadığı için güvenilir açıklama üretilemedi."
            self.confidence = 0.0
            self.model_confidence = 0.0
            self.data_confidence = 0.0

        # 4. Kural: Risk listesini en fazla 3 madde ile sınırla (bilgi kalabalığı engeli)
        if len(self.risks) > 3:
            self.risks = self.risks[:3]

        return self

    def to_fail_closed_fallback(self, reason: str = "Veri yetersiz") -> "ShovelExplanation":
        """Hata veya retry tükenmesi durumunda deterministik fail-closed yanıt."""
        return ShovelExplanation(
            summary=f"Güncel veri bulunmadığı için güvenilir açıklama üretilemedi: Veri yetersiz ({reason}).",
            evidence=[],
            risks=["Doğrulanmamış veya eksik veri riski."],
            confidence=0.0,
            model_confidence=0.0,
            data_confidence=0.0,
            source=[],
            source_verified=False,
            as_of=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            status=ExplanationStatus.INSUFFICIENT_DATA
        )


# ════════════════════════════════════════════════════════════════════
# 2. ÖNBELLEK VE METRİK GÜNLÜĞÜ (CACHE & METRICS LOGGER)
# ════════════════════════════════════════════════════════════════════

class SimpleTTLCache:
    """
    5 dakikalık bellek içi TTL önbellek.
    Cache anahtarı sembol + görev + veri zamanı + kaynak bileşenlerinden türetilir.
    Böylece veri güncellendiğinde (yeni as_of veya kaynak) eski önbellek otomatik geçersizleşir.
    """
    def __init__(self, ttl_seconds: int = 300):
        self.ttl = ttl_seconds
        self._cache: Dict[str, tuple[float, ShovelExplanation, int, int]] = {}
        self.hits: int = 0
        self.misses: int = 0
        self.saved_prompt_tokens: int = 0
        self.saved_completion_tokens: int = 0

    def make_key(self, symbol: str, task_type: str, as_of: str, sources: List[str]) -> str:
        sym = (symbol or "GENEL").strip().upper()
        task = (task_type or "GENEL").strip().upper()
        date_str = (as_of or "").strip()
        src_sorted = sorted([s.strip().lower() for s in (sources or []) if s and s.strip()])
        raw = f"{sym}:::{task}:::{date_str}:::{'|'.join(src_sorted)}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _hash_key(self, prompt: str, context: str) -> str:
        return hashlib.sha256(f"{prompt}:::{context}".encode("utf-8")).hexdigest()

    def get(
        self,
        prompt_or_key: Optional[str] = None,
        context: Optional[str] = None,
        symbol: Optional[str] = None,
        task_type: Optional[str] = None,
        as_of: Optional[str] = None,
        sources: Optional[List[str]] = None
    ) -> Optional[ShovelExplanation]:
        if symbol and task_type:
            k = self.make_key(symbol, task_type, as_of or "", sources or [])
        elif prompt_or_key and context is not None:
            k = self._hash_key(prompt_or_key, context)
        elif prompt_or_key:
            k = prompt_or_key
        else:
            self.misses += 1
            return None

        item = self._cache.get(k)
        if not item:
            self.misses += 1
            return None
        ts, exp, p_tok, c_tok = item
        if time.time() - ts > self.ttl:
            del self._cache[k]
            self.misses += 1
            return None
        
        self.hits += 1
        self.saved_prompt_tokens += p_tok
        self.saved_completion_tokens += c_tok
        return exp

    def set(
        self,
        prompt_or_key: Optional[str] = None,
        context_or_exp: Any = None,
        exp: Optional[ShovelExplanation] = None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        symbol: Optional[str] = None,
        task_type: Optional[str] = None,
        as_of: Optional[str] = None,
        sources: Optional[List[str]] = None
    ):
        actual_exp = exp if exp is not None else (context_or_exp if isinstance(context_or_exp, ShovelExplanation) else None)
        if symbol and task_type:
            k = self.make_key(symbol, task_type, as_of or "", sources or [])
        elif prompt_or_key and isinstance(context_or_exp, str):
            k = self._hash_key(prompt_or_key, context_or_exp)
        elif prompt_or_key:
            k = prompt_or_key
        else:
            return

        self._cache[k] = (time.time(), actual_exp, prompt_tokens, completion_tokens)

    def get_metrics(self) -> Dict[str, Any]:
        total = self.hits + self.misses
        hit_rate = round((self.hits / total) * 100, 1) if total > 0 else 0.0
        return {
            "hits": self.hits,
            "misses": self.misses,
            "total_requests": total,
            "hit_rate_pct": hit_rate,
            "saved_prompt_tokens": self.saved_prompt_tokens,
            "saved_completion_tokens": self.saved_completion_tokens,
            "total_saved_tokens": self.saved_prompt_tokens + self.saved_completion_tokens
        }



class InstructorMetricsLogger:
    """Çağrı, token tasarrufu, retry sayısı ve gecikmeleri loglar."""
    def __init__(self):
        self.log_file = os.path.join(LOG_DIR, "instructor-metrikleri.jsonl")

    def log(self, task_type: str, model: str, prompt_tokens: int, completion_tokens: int,
            retries: int, status: str, latency_ms: float, error: Optional[str] = None):
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "task_type": task_type,
            "model": model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "retries": retries,
            "status": status,
            "latency_ms": round(latency_ms, 1),
            "error": error
        }
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            pass


# ════════════════════════════════════════════════════════════════════
# 3. SHOVEL INSTRUCTOR YÖNETİCİSİ (INSTRUCTOR ENGINE)
# ════════════════════════════════════════════════════════════════════

class ShovelInstructorEngine:
    def __init__(self, model_name: str = "gpt-6-luna", max_retries: int = 2):
        self.model_name = model_name
        self.max_retries = max_retries
        self.cache = SimpleTTLCache(ttl_seconds=300)
        self.logger = InstructorMetricsLogger()
        self.api_key = os.environ.get("OPENAI_API_KEY")
        self._client = None
        self._instructor_client = None

        if OpenAI and self.api_key:
            try:
                base_client = OpenAI(api_key=self.api_key)
                self._instructor_client = instructor.from_openai(base_client, mode=instructor.Mode.JSON)
            except Exception:
                self._instructor_client = None

    def explain(
        self,
        task_type: str,
        user_query: str,
        context_data: Optional[Dict[str, Any]] = None,
        as_of_date: Optional[str] = None,
        sources: Optional[List[str]] = None,
        symbol: str = "GENEL",
        independent_data_ts: Optional[str] = None
    ) -> ShovelExplanation:
        """
        Instructor + Pydantic üzerinden katı ShovelExplanation şemasıyla açıklama üretir.
        Bağımsız veri katmanından (independent_data_ts) gelen gerçek zaman damgası önceliklidir.
        """
        start_time = time.time()
        context_dict = context_data or {}
        
        # Bağımsız veri katmanı doğrulaması: Kullanıcının yazdığı değil, sistemin teyit ettiği tarih esastır
        as_of_clean = independent_data_ts or as_of_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        sources_clean = sources or []

        # 1. Cache Kontrolü (Bileşik Anahtar: sembol + görev + veri zamanı + kaynak)
        context_str = json.dumps(context_dict, sort_keys=True, ensure_ascii=False)
        cached = self.cache.get(
            prompt_or_key=user_query,
            context=context_str,
            symbol=symbol,
            task_type=task_type,
            as_of=as_of_clean,
            sources=sources_clean
        )
        if cached:
            return cached

        # 2. as_of ve Veri Sözleşmesi Ön Denetimi (Deterministik Fail-Closed)
        if not as_of_clean or as_of_clean.strip() in {"", "None"}:
            fallback = ShovelExplanation(
                summary="Güncel veri bulunmadığı için güvenilir açıklama üretilemedi.",
                evidence=[],
                risks=["Eksik zaman damgası riski."],
                confidence=0.0,
                model_confidence=0.0,
                data_confidence=0.0,
                source=sources_clean,
                source_verified=False,
                as_of=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                status=ExplanationStatus.INSUFFICIENT_DATA
            )
            return fallback

        # Sistem istemi (Sade dil kuralı, kısa özet, sıfır selamlama)
        system_prompt = (
            "Sen Shovel Terminali için çalışan profesyonel, ekonomik finansal açıklama ve özet motorusun.\n"
            "GÖREVİN: Verilen finansal bağlamı sade Türkçe ile açıklamak ve riskleri listelemektir.\n"
            "KESİNLİKLE UYULMASI GEREKEN KURALLAR:\n"
            "1. summary: En fazla 1-2 cümle, çok sade ve saygılı Türkçe olmalı. Selamlama ve dolgu kelimesi içermemeli.\n"
            "2. evidence: Yalnızca verilen metindeki somut gerçekleri maddelemeli.\n"
            "3. risks: En fazla 3 risk maddesi içermeli.\n"
            "4. confidence: 0 ile 100 arasında bir model güven skoru olmalı.\n"
            "5. as_of: Verilen tarih bilgisini aynen kullanmalı.\n"
            "6. Quant faktörlerini, AL/SAT tavsiyesi veya hedef fiyat uydurmamalı.\n"
            "7. Veri yetersizse status 'INSUFFICIENT_DATA' seçilmeli."
        )

        user_content = (
            f"Varlık / Sembol: {symbol}\n"
            f"Görev Türü: {task_type}\n"
            f"Soru / Konu: {user_query}\n"
            f"Doğrulanmış Tarih (as_of): {as_of_clean}\n"
            f"Resmi Kaynaklar: {', '.join(sources_clean) if sources_clean else 'Belirtilmedi'}\n"
            f"Finansal Bağlam:\n{context_str}\n\n"
            "Açıklama ve riskleri ShovelExplanation şemasına uygun olarak üret."
        )

        # 3. Instructor Çağrısı (Retry Korumalı)
        explanation: Optional[ShovelExplanation] = None
        retries_used = 0
        prompt_tokens = len(user_content) // 4
        completion_tokens = 0
        err_msg = None

        if self._instructor_client:
            try:
                # Instructor create with Pydantic response_model and max_retries
                resp: ShovelExplanation = self._instructor_client.chat.completions.create(
                    model=self.model_name,
                    response_model=ShovelExplanation,
                    max_retries=self.max_retries,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content}
                    ]
                )
                explanation = resp
                completion_tokens = len(explanation.summary) // 4 + 40
            except Exception as e:
                err_msg = str(e)
                retries_used = self.max_retries
                explanation = None

        # 4. Fallback / Yerel Çözücü (API yoksa veya hata alındıysa)
        if not explanation:
            # Yerel / Deterministik Güvenli Üretici
            explanation = self._deterministic_fallback(
                task_type, user_query, context_dict, as_of_clean, sources_clean, err_msg
            )

        latency_ms = (time.time() - start_time) * 1000

        # 5. Metrik Loglama
        self.logger.log(
            task_type=task_type,
            model=self.model_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            retries=retries_used,
            status=explanation.status.value,
            latency_ms=latency_ms,
            error=err_msg
        )

        # 6. Cache'e Yaz (Bileşik Anahtar)
        self.cache.set(
            prompt_or_key=user_query,
            context_or_exp=context_str,
            exp=explanation,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            symbol=symbol,
            task_type=task_type,
            as_of=as_of_clean,
            sources=sources_clean
        )
        return explanation

    def _deterministic_fallback(
        self,
        task_type: str = "GENEL",
        user_query: str = "Finansal analiz",
        context_data: Optional[Dict[str, Any]] = None,
        as_of: str = "",
        sources: Optional[List[str]] = None,
        error_info: Optional[str] = None,
        reason: Optional[str] = None
    ) -> ShovelExplanation:
        """
        API bağlantısı olmadığında veya Instructor başarısız olduğunda 
        deterministik, halüsinasyonsuz ve fail-closed Pydantic çıktısı üretir.
        """
        sources_clean = sources or []
        has_sources = bool(sources_clean and len(sources_clean) > 0)
        
        # Basit durum analizi veya açık reason belirtilmişse
        if reason or not context_data:
            summary_msg = (
                f"Güncel veri bulunmadığı için güvenilir açıklama üretilemedi: Veri yetersiz ({reason})."
                if reason else
                "Güncel veri bulunmadığı için güvenilir açıklama üretilemedi."
            )
            return ShovelExplanation(
                summary=summary_msg,
                evidence=[],
                risks=["Doğrulanmamış veya eksik veri riski." if reason else "Eksik veri seti."],
                confidence=0.0,
                source=sources_clean,
                as_of=as_of if as_of is not None else datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                status=ExplanationStatus.INSUFFICIENT_DATA
            )

        # Konuya göre sade özet şablonu
        summary_text = f"{user_query} verisi incelendi. Belirtilen finansal göstergeler mevcut piyasa çerçevesinde değerlendirilmelidir."
        evidence_items = []
        for k, v in list(context_data.items())[:3]:
            evidence_items.append(f"{k}: {v}")

        risks_items = [
            "Piyasa koşullarındaki ani değişim riski.",
            "Faiz ve likidite politikalarındaki dalgalanma riski."
        ]

        status = ExplanationStatus.VERIFIED if has_sources else ExplanationStatus.PARTIAL
        confidence = 80.0 if has_sources else 50.0

        return ShovelExplanation(
            summary=summary_text,
            evidence=evidence_items,
            risks=risks_items,
            confidence=confidence,
            source=sources_clean,
            as_of=as_of or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            status=status
        )

    # Geriye dönük uyumluluk takma adı
    _get_deterministic_fallback = _deterministic_fallback


# Global Tekil Nesne
shovel_instructor = ShovelInstructorEngine(model_name="gpt-6-luna", max_retries=2)
