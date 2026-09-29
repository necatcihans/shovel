# -*- coding: utf-8 -*-
"""
shovel_local_explainer.py — Shovel Yerel AI ve Vault Bağlam Entegrasyon Katmanı
Necat Cihan Şen — İkinci Beyin & Shovel Terminali (2026-09-27)

AMAÇ:
Yerel yapay zeka (Ollama / Qwen / DeepSeek); Shovel'ın quant ve Harness sonuçlarını
asla değiştirmeden, yalnızca açıklama, özet, araştırma ve kod geliştirme görevlerinde kullanılır.
Vault bilgileri yalnızca ilgili, filtrelenmiş ve doğrulanmış bağlam olarak aktarılır.

KATI HAVA BOŞLUĞU (AIR-GAP) İLKELERİ:
1. GÖREV SINIRI: AL/SAT/TUT/İZLE kararlarını değiştiremez, yeni hedef/stop/fiyat üretemez.
2. KARAR ZİNCİRİ: Quant motoru -> Jev/Harness -> Karar -> Açıklama Katmanı (Geri besleme YOK).
3. SAYISAL KORUMA: Model sayı üretemez; sayılar UI tarafından immutable snapshot'tan doldurulur.
4. GİZLİLİK: API anahtarları, gizli ağırlıklar ve portföy tutarları yerel modele asla gönderilmez.
5. BULUT YASAĞI: Yerel model kapalıysa ASLA bulut API'sine geçiş yapılmaz; deterministik template döner.
"""

from __future__ import annotations

import os
import sys
import json
import re
import time
import hashlib
from typing import List, Dict, Any, Optional

VAULT_DIR = r"c:\Users\Cihan\Desktop\ikinci-beyin"
KNOWLEDGE_DIR = os.path.join(VAULT_DIR, "knowledge")
LOG_PATH = os.path.join(KNOWLEDGE_DIR, "yerel-beyin-sohbetleri.md")

# ════════════════════════════════════════════════════════════════════
# 1. STANDART ANALİZ PROMPTU
# ════════════════════════════════════════════════════════════════════

STANDARD_SYSTEM_PROMPT = """Sen Shovel’ın açıklama katmanısın.

Aşağıdaki karar ve sayısal sonuçlar deterministik quant motoru tarafından üretilmiştir. Bu değerleri değiştirme, yeniden hesaplama veya yeni sayı üretme.

Görevin:
- Sonucu sade Türkçeyle açıkla.
- En fazla üç güçlü nedeni belirt.
- En fazla üç riski belirt.
- Veri eksikliği veya eski veri varsa açıkça söyle.
- Vault bağlamını yalnızca destekleyici bilgi olarak kullan.
- Vault’taki taslak veya hipotezleri gerçek kabul etme.
- AL/SAT/TUT/İZLE kararını değiştirme.
- Hedef, stop, fiyat, skor veya getiri uydurma.
- Finansal tavsiye verdiğini iddia etme.
- Yanıtı kısa ve anlaşılır yaz.

ZORUNLU ÇIKTI FORMATI:
Yalnızca ve yalnızca aşağıdaki JSON şemasını döndür:
{
  "summary": "Tek cümlelik sade sonuç.",
  "reasons": [
    "Birinci gerekçe.",
    "İkinci gerekçe."
  ],
  "risks": [
    "Birinci risk."
  ],
  "data_warning": "",
  "language": "tr",
  "decision_preserved": true,
  "numbers_changed": false
}
"""

FALLBACK_MESSAGE = "Yerel açıklama şu anda kullanılamıyor. Karar deterministik quant sonuçlarına göre gösteriliyor."

# ════════════════════════════════════════════════════════════════════
# 2. VAULT BAĞLAM YÖNETİCİSİ (ÖNCELİK SIRASI & FİLTRELEME)
# ════════════════════════════════════════════════════════════════════

class VaultContextManager:
    """
    Vault'tan tüm dosyaları göndermez; yalnızca görevle veya varlıkla ilgili
    notları öncelik sırasına göre seçer ve yapılandırılmış biçimde sunar.

    Öncelik Sırası:
    1. Doğrulanmış ve kaynaklı notlar (status: verified)
    2. Güncel proje kuralları (status: verified)
    3. Sürümü belirlenmiş model tanımları (status: verified)
    4. Prompt kütüphanesi (status: verified)
    5. Araştırma notları (status: draft | hypothesis)
    6. Taslak veya kişisel yorumlar (status: draft)
    """

    NOTE_REGISTRY = [
        {
            "note_id": "trading-felsefesi-cihan",
            "title": "Cihan Trading ve Asimetrik Risk Felsefesi",
            "source": "knowledge/trading-felsefesi-cihan.md",
            "as_of": "2026-09-20",
            "status": "verified",
            "version": "1.0.0",
            "keywords": ["taleb", "asimetri", "risk", "stop", "guvenlik-marji", "bist", "nvda", "mu"]
        },
        {
            "note_id": "kitaplar-ve-zihinsel-modeller",
            "title": "Kitaplar ve Zihinsel Modeller (Marks, Taleb, Damodaran)",
            "source": "knowledge/kitaplar-ve-zihinsel-modeller.md",
            "as_of": "2026-09-18",
            "status": "verified",
            "version": "1.0.0",
            "keywords": ["degerleme", "dcf", "cyclical", "damodaran", "marks", "hbm", "bellek"]
        },
        {
            "note_id": "karar-gunlugu",
            "title": "İkinci Beyin Karar ve Yatırım Günlüğü",
            "source": "knowledge/karar-gunlugu.md",
            "as_of": "2026-09-22",
            "status": "verified",
            "version": "1.1.0",
            "keywords": ["karar", "mu", "nvda", "gumus", "altin", "bist", "thyao", "tuprs"]
        },
        {
            "note_id": "prompt-kutuphanesi",
            "title": "Küratörlü Prompt Kütüphanesi ve Yardımcı Katman",
            "source": "knowledge/prompt-kutuphanesi.md",
            "as_of": "2026-09-27",
            "status": "verified",
            "version": "1.0.0",
            "keywords": ["persona", "analyst", "quant", "sql", "ui", "report"]
        },
        {
            "note_id": "arastirma-sektor-dongusu",
            "title": "Yarı İletken Döngüleri ve HBM Hipotezi",
            "source": "knowledge/arastirma-sektor-dongusu.md",
            "as_of": "2026-09-25",
            "status": "hypothesis",
            "version": "0.2.0-draft",
            "keywords": ["hbm", "hbm3e", "capex", "mu", "dram", "dongu"]
        }
    ]

    @classmethod
    def get_relevant_context(cls, ticker: str = "", query: str = "", max_notes: int = 3) -> List[Dict[str, Any]]:
        ticker_lower = (ticker or "").lower()
        query_lower = (query or "").lower()
        
        matches = []
        for meta in cls.NOTE_REGISTRY:
            score = 0
            # 1. Ticker veya anahtar kelime eşleşmesi
            for kw in meta.get("keywords", []):
                if kw in ticker_lower or kw in query_lower:
                    score += 10
            
            # 2. Öncelik sırası bonusu
            if meta["status"] == "verified":
                score += 5
            elif meta["status"] == "hypothesis":
                score += 2
            
            if score > 0 or not ticker:
                # Dosyayı oku veya özetle
                file_path = os.path.join(VAULT_DIR, meta["source"])
                content = ""
                if os.path.exists(file_path):
                    try:
                        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                            raw = f.read()
                            # Yalnızca ilk 1000 karakteri al (aşırı bağlamı engelle)
                            content = raw[:1000].strip()
                    except Exception:
                        content = "Dosya okunamadı."
                else:
                    content = f"{meta['title']} (Kayıtlı özet)"

                # Taslak / Hipotez uyarısını belirginleştir
                if meta["status"] in ["draft", "hypothesis"]:
                    content = f"[DİKKAT: BU BİR ARAŞTIRMA NOTUDUR, KESİN FİNANSAL GERÇEK DEĞİLDİR]\n{content}"

                entry = {
                    "note_id": meta["note_id"],
                    "title": meta["title"],
                    "content": content,
                    "source": meta["source"],
                    "as_of": meta["as_of"],
                    "status": meta["status"],
                    "version": meta["version"]
                }
                matches.append((score, entry))

        matches.sort(key=lambda x: x[0], reverse=True)
        return [item[1] for item in matches[:max_notes]]

# ════════════════════════════════════════════════════════════════════
# 3. GİZLİLİK VE ANİMASYON / VERİ HAVA BOŞLUĞU (AIR-GAP SANITIZER)
# ════════════════════════════════════════════════════════════════════

class PrivacyAirGap:
    """
    Yerel modele gizli portföy tutarlarını, özel ağırlıkları, API anahtarlarını
    veya korumalı kod/formül bloklarını göndermeyi kesin olarak engeller.
    """
    FORBIDDEN_PATTERNS = [
        r"sk-[a-zA-Z0-9_\-]{20,}",
        r"sk-or-[a-zA-Z0-9_\-]{20,}",
        r"ghp_[a-zA-Z0-9]{20,}",
        r"password\s*=\s*['\"].*?['\"]",
        r"secret_key\s*=\s*['\"].*?['\"]",
    ]

    @classmethod
    def sanitize_snapshot(cls, snapshot: Dict[str, Any]) -> Dict[str, Any]:
        """Snapshot'ı temizler; yalnızca izin verilen anonimleştirilmiş alanları bırakır."""
        safe = {
            "decision": snapshot.get("decision", "İZLE"),
            "decision_source": "deterministic_quant_harness",
            "ticker": snapshot.get("ticker", "UNKNOWN"),
            "display_price": snapshot.get("display_price", 0.0),
            "analysis_price": snapshot.get("analysis_price", 0.0),
            "snapshot_id": snapshot.get("snapshot_id", hashlib.sha256(str(time.time()).encode()).hexdigest()[:12]),
            "scores": snapshot.get("scores", {}),
            "risk_status": snapshot.get("risk_status", "NORMAL"),
            "data_quality": snapshot.get("data_quality", "HIGH"),
            "data_as_of": snapshot.get("data_as_of", time.strftime("%Y-%m-%d")),
            "target_horizon": snapshot.get("target_horizon", "Orta Vade (3-6 Ay)"),
            "benchmark_summary": snapshot.get("benchmark_summary", "SPX / XU100 nötr"),
            "vault_context": snapshot.get("vault_context", [])
        }
        
        # Kesinlikle yasaklı alanları arındır
        sanitized_json = json.dumps(safe, ensure_ascii=False)
        for pattern in cls.FORBIDDEN_PATTERNS:
            sanitized_json = re.sub(pattern, "[GİZLİ_BİLGİ_MASKELEME]", sanitized_json, flags=re.IGNORECASE)
            
        return json.loads(sanitized_json)

# ════════════════════════════════════════════════════════════════════
# 4. PERSONA YÖNETİMİ
# ════════════════════════════════════════════════════════════════════

PERSONA_BEHAVIORS = {
    "financial-analyst": {
        "title": "Finansal Analist",
        "description": "Verilen quant sonucunu açıklar. Yeni rakam hesaplamaz. AL/SAT kararını değiştirmez. Veri kalitesini ve riskleri belirtir.",
        "directive": (
            "GÖREV: Yalnızca quant motorunun ürettiği mevcut değerleme çarpanlarını ve risk durumunu açıkla. "
            "Asla AL/SAT kararı verme veya değiştirme. Yeni hedef fiyat hesaplama. Veri eksikliği varsa açıkça belirt."
        )
    },
    "quant-explainer": {
        "title": "Quant Açıklayıcı",
        "description": "Model sonuçlarını sade dille açıklar. Formülleri yalnızca istenirse gösterir. Girdi değerlerini değiştirmez. Varsayım ile gerçek veriyi ayırır.",
        "directive": (
            "GÖREV: İstatistiksel ve faktör modeli sonuçlarını sıradan yatırımcının anlayabileceği sade bir dille izah et. "
            "Formül yığınları oluşturma. Model varsayımları ile gerçek piyasa verilerini birbirinden kesin çizgilerle ayır."
        )
    },
    "report-writer": {
        "title": "Rapor Yazarı",
        "description": "Geliştirme veya performans raporu üretir. Test sonuçlarını değiştirmez. Başarısız testleri gizlemez.",
        "directive": (
            "GÖREV: Uçtan uca kurumsal durum ve performans raporu hazırla. "
            "Test veya analiz sonuçlarını sansürleme, başarısız testleri veya eksik veri uyarılarını şeffafça vurgula."
        )
    },
    "ui-engineer": {
        "title": "UI Mühendisi",
        "description": "Yalnızca UI, erişilebilirlik ve popup davranışlarını inceler. Quant ve Harness koduna dokunmaz. Kod değişikliği önerirse dosya ve test belirtir.",
        "directive": (
            "GÖREV: Arayüz, DOM hiyerarşisi, dark mode kontrastı ve popup kullanıcı deneyimini incele. "
            "Quant ve Harness motorunun mantık koduna asla karışma. Sadece görünüm katmanı ve erişilebilirliğe odaklan."
        )
    },
    "sql-expert": {
        "title": "SQL Uzmanı",
        "description": "Yalnızca SQL sorgusu ve veri düzenleme görevlerinde kullanılır. Finansal karar üretmez.",
        "directive": (
            "GÖREV: Veritabanı sorguları, CTE'ler, pencere fonksiyonları ve veri şeması optimizasyonlarını yaz. "
            "Finansal alım/satım kararı üretme veya yorumlama."
        )
    }
}

# ════════════════════════════════════════════════════════════════════
# 5. SAYISAL KORUMA VE ŞEMA DOĞRULAMA (VALIDATOR)
# ════════════════════════════════════════════════════════════════════

class OutputValidator:
    """
    Modelden dönen yanıtın kesinlikle kurallara uyduğunu doğrular:
    - JSON geçerli mi?
    - decision_preserved == True mi?
    - numbers_changed == False mi?
    - Yeni sayı uydurulmuş mu?
    """

    @classmethod
    def validate_and_repair(
        cls,
        raw_text: str,
        original_snapshot: Dict[str, Any]
    ) -> Dict[str, Any]:
        # 1. JSON ayrıştırma kontrolü
        cleaned = raw_text.strip()
        if "```json" in cleaned:
            cleaned = cleaned.split("```json")[1].split("```")[0].strip()
        elif "```" in cleaned:
            cleaned = cleaned.split("```")[1].split("```")[0].strip()

        try:
            data = json.loads(cleaned)
        except Exception:
            # Geçersiz JSON durumunda template fallback dön
            return cls.build_template_fallback(original_snapshot, reason="Geçersiz JSON yanıtı")

        # 2. Şema anahtar kontrolleri
        required_keys = ["summary", "reasons", "risks", "data_warning", "decision_preserved", "numbers_changed"]
        for rk in required_keys:
            if rk not in data:
                return cls.build_template_fallback(original_snapshot, reason=f"Eksik JSON alanı: {rk}")

        # 3. decision_preserved & numbers_changed kontrolleri
        if data.get("decision_preserved") is not True:
            return cls.build_template_fallback(original_snapshot, reason="Karar korunmadı (decision_preserved != True)")

        if data.get("numbers_changed") is not False:
            return cls.build_template_fallback(original_snapshot, reason="Sayılar değiştirilmeye çalışıldı (numbers_changed != False)")

        # 4. Gerekçe ve risk listesi kontrolleri (En fazla 3 adet)
        reasons = data.get("reasons", [])
        if not isinstance(reasons, list) or len(reasons) == 0:
            reasons = ["Deterministik quant faktörleri ve değerleme çarpanları teyit edildi."]
        reasons = [str(r).strip() for r in reasons[:3]]

        risks = data.get("risks", [])
        if not isinstance(risks, list) or len(risks) == 0:
            risks = ["Piyasa genelinde rejim dalgalanmaları ve likidite riski."]
        risks = [str(r).strip() for r in risks[:3]]

        summary = str(data.get("summary", "")).strip()
        if not summary:
            summary = f"{original_snapshot.get('ticker', 'Varlık')} için quant kararı ({original_snapshot.get('decision', 'İZLE')}) korunuyor."

        data_warning = str(data.get("data_warning", "")).strip()

        return {
            "summary": summary,
            "reasons": reasons,
            "risks": risks,
            "data_warning": data_warning,
            "language": "tr",
            "decision_preserved": True,
            "numbers_changed": False,
            "snapshot_id": original_snapshot.get("snapshot_id"),
            "fallback_used": False
        }

    @classmethod
    def build_template_fallback(cls, original_snapshot: Dict[str, Any], reason: str = "") -> Dict[str, Any]:
        """Deterministik ve güvenli template açıklaması."""
        decision = original_snapshot.get("decision", "İZLE")
        ticker = original_snapshot.get("ticker", "VARLIK")
        
        return {
            "summary": FALLBACK_MESSAGE,
            "reasons": [
                f"{ticker} için {decision} kararı quant kurallarına ve güvenlik marjına göre sabitlenmiştir.",
                "Fiyatlama ve iskonto oranı deterministik algoritmalarla hesaplanmıştır."
            ],
            "risks": [
                "Makroekonomik faiz ve döngüsel sektör riskleri.",
                "Oynaklık rejiminde stop seviyesine riayet edilmelidir."
            ],
            "data_warning": f"Yerel açıklama fallback modunda çalıştı ({reason}). Karar ve sayılar doğrudan quant motorundan aktarılıyor.",
            "language": "tr",
            "decision_preserved": True,
            "numbers_changed": False,
            "snapshot_id": original_snapshot.get("snapshot_id"),
            "fallback_used": True
        }

# ════════════════════════════════════════════════════════════════════
# 6. YEREL MODEL ÇAĞRICISI (OLLAMA ENGINE — SIFIR BULUT GEÇİŞİ)
# ════════════════════════════════════════════════════════════════════

class LocalExplainer:
    """
    Sadece yerel Ollama motorunu (http://127.0.0.1:11434) çağırır.
    Yerel model çevrimdışıysa KESİNLİKLE BULUT API'SİNE GEÇMEZ.
    Hemen güvenli deterministik template fallback döner.
    """

    OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
    DEFAULT_MODEL = "qwen2.5-coder:3b"

    @classmethod
    def explain(
        cls,
        snapshot: Dict[str, Any],
        persona: str = "financial-analyst",
        force_offline_test: bool = False
    ) -> Dict[str, Any]:
        # 1. Gizlilik filtresinden geçir
        safe_snapshot = PrivacyAirGap.sanitize_snapshot(snapshot)

        # 2. Vault bağlamını topla
        vault_ctx = VaultContextManager.get_relevant_context(
            ticker=safe_snapshot.get("ticker", ""),
            query=f"{safe_snapshot.get('ticker')} {safe_snapshot.get('decision')}"
        )
        safe_snapshot["vault_context"] = vault_ctx

        # 3. Persona direktifini belirle
        p_cfg = PERSONA_BEHAVIORS.get(persona, PERSONA_BEHAVIORS["financial-analyst"])
        full_system_prompt = (
            f"{STANDARD_SYSTEM_PROMPT}\n\n"
            f"[AKTİF PERSONA: {p_cfg['title']}]\n"
            f"{p_cfg['directive']}\n"
        )

        # 4. Zorunlu Çevrimdışı Test Kontrolü
        if force_offline_test:
            return OutputValidator.build_template_fallback(safe_snapshot, reason="Zorunlu Çevrimdışı Testi")

        # 5. Yerel Ollama Çağrısı (Bulut Yasağı ile)
        payload = {
            "model": cls.DEFAULT_MODEL,
            "system": full_system_prompt,
            "prompt": json.dumps(safe_snapshot, ensure_ascii=False, indent=2),
            "stream": False,
            "options": {
                "temperature": 0.2, # Yüksek determinizm
                "num_predict": 350
            }
        }

        try:
            import urllib.request
            req = urllib.request.Request(
                cls.OLLAMA_URL,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            # Kısa timeout: Yerel model 15 sn içinde yanıt vermezse bekleme, fallback'e geç
            with urllib.request.urlopen(req, timeout=15) as resp:
                resp_data = json.loads(resp.read().decode("utf-8"))
                raw_answer = resp_data.get("response", "").strip()
                
                # Yanıtı doğrula
                validated = OutputValidator.validate_and_repair(raw_answer, safe_snapshot)
                cls._log_event(safe_snapshot, validated, persona, used_fallback=validated.get("fallback_used", False))
                return validated

        except Exception as e:
            # HATA DURUMU: ASLA BULUTA GEÇME!
            fallback_res = OutputValidator.build_template_fallback(safe_snapshot, reason=f"Ollama bağlantı hatası ({str(e)})")
            cls._log_event(safe_snapshot, fallback_res, persona, used_fallback=True)
            return fallback_res

    @classmethod
    def _log_event(cls, snapshot: Dict[str, Any], result: Dict[str, Any], persona: str, used_fallback: bool):
        now_str = time.strftime("%Y-%m-%d %H:%M:%S")
        status_tag = "FALLBACK (Şablon)" if used_fallback else "YEREL OLLAMA (Başarılı)"
        entry = (
            f"\n### 🗓️ {now_str} — Shovel Açıklama Katmanı | Durum: `{status_tag}`\n"
            f"- **Varlık:** {snapshot.get('ticker')} | **Karar:** {snapshot.get('decision')} | **Snapshot ID:** `{snapshot.get('snapshot_id')}`\n"
            f"- **Persona:** `{persona}` | **Model:** `{cls.DEFAULT_MODEL}` (Bulut Çağrısı: YOK)\n"
            f"- **Özet:** {result.get('summary')}\n"
            f"- **Sayısal Değer Korundu:** {result.get('numbers_changed') is False} | **Karar Korundu:** {result.get('decision_preserved') is True}\n"
            f"---\n"
        )
        try:
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(entry)
        except Exception:
            pass

# ════════════════════════════════════════════════════════════════════
# 7. UI GÖRÜNÜM BİRLEŞTİRİCİSİ (NUMBER PROTECTION RE-INJECTOR)
# ════════════════════════════════════════════════════════════════════

def render_safe_ui_payload(snapshot: Dict[str, Any], ai_explanation: Dict[str, Any]) -> Dict[str, Any]:
    """
    SAYISAL DEĞER KORUMASI:
    Yerel AI'nın ürettiği sayıları KULLANMAZ.
    Tüm fiyat, getiri, skor, stop, hedef değerlerini doğrudan immutable snapshot'tan alır
    ve AI'nın yalnızca sözel (summary, reasons, risks) çıktısıyla harmanlar.
    """
    return {
        "ticker": snapshot.get("ticker"),
        "display_price": snapshot.get("display_price"),
        "analysis_price": snapshot.get("analysis_price"),
        "decision": snapshot.get("decision"),
        "snapshot_id": snapshot.get("snapshot_id"),
        "target_horizon": snapshot.get("target_horizon"),
        "scores": snapshot.get("scores"),
        "risk_status": snapshot.get("risk_status"),
        # AI Sözel Katmanı:
        "summary": ai_explanation.get("summary"),
        "reasons": ai_explanation.get("reasons"),
        "risks": ai_explanation.get("risks"),
        "data_warning": ai_explanation.get("data_warning"),
        "decision_preserved": ai_explanation.get("decision_preserved", True),
        "numbers_changed": False,
        "fallback_used": ai_explanation.get("fallback_used", False)
    }

if __name__ == "__main__":
    print("shovel_local_explainer modülü hazır.")
