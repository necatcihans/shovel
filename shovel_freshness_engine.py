# -*- coding: utf-8 -*-
"""
shovel_freshness_engine.py — Shovel Veri Tazeliği, Fallback, Retry, Prefetch ve Kaynak Sağlık Sistemi

KAPSAM:
1. Kaynak Bazlı Staleness SLA Denetimi (price_equity, price_crypto, price_fx, technical, balance_sheet, macro, news, funding_open_interest)
2. Üstel Geri Çekilme (Exponential Backoff) ile Otomatik Yeniden Deneme (Retry Engine)
3. Kaynak Sağlık Skoru ve Devre Kesici (Circuit Breaker: HEALTHY, DEGRADED, DOWN)
4. Arka Plan Prefetch & Önbellek Isıtma (Cache Warmup)
5. Veri Yaşı, Tazelik ve Kalite Metriklerinin Standardize Edilmesi
"""

from __future__ import annotations

import os
import sys
import json
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Tuple, Literal, Callable

# UTF-8 stdout
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

VAULT_DIR = r"c:\Users\Cihan\Desktop\ikinci-beyin"
CONFIG_DIR = os.path.join(VAULT_DIR, "config")
JOURNAL_DIR = os.path.join(VAULT_DIR, "journal")
SLA_CONFIG_FILE = os.path.join(CONFIG_DIR, "data_freshness_sla.json")
HEALTH_LOG_FILE = os.path.join(JOURNAL_DIR, "provider_health_events.jsonl")

os.makedirs(CONFIG_DIR, exist_ok=True)
os.makedirs(JOURNAL_DIR, exist_ok=True)


def load_sla_config() -> Dict[str, Any]:
    if os.path.exists(SLA_CONFIG_FILE):
        try:
            with open(SLA_CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "freshness_sla": {
            "price_equity": {"max_age_seconds": 120, "critical": True},
            "price_crypto": {"max_age_seconds": 30, "critical": True},
            "price_fx": {"max_age_seconds": 120, "critical": True},
            "technical": {"max_age_seconds": 300, "critical": True},
            "balance_sheet": {"max_age_seconds": 2592000, "critical": False},
            "macro": {"max_age_seconds": 7776000, "critical": False},
            "news": {"max_age_seconds": 21600, "critical": False},
            "funding_open_interest": {"max_age_seconds": 300, "critical": True}
        },
        "retry_policy": {
            "max_retries": 3,
            "initial_delay_ms": 300,
            "backoff_multiplier": 1.5,
            "timeout_ms": 4000
        },
        "circuit_breaker": {
            "failure_threshold": 3,
            "recovery_time_seconds": 60,
            "degraded_threshold_error_rate": 0.25
        }
    }


# ════════════════════════════════════════════════════════════════════
# 1. KAYNAK BAZLI STALENESS SLA DENETÇİSİ
# ════════════════════════════════════════════════════════════════════

class FreshnessSLAManager:
    """Veri kategorisine göre SLA sınırını denetler ve kalite durumu atar."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or load_sla_config()
        self.sla_rules = self.config.get("freshness_sla", {})

    def check_staleness(
        self,
        category: str,
        as_of_timestamp: str,
        current_time: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        Kategoriye göre yaş hesabı ve durum etiketi:
        - FRESH: age <= max_age
        - DELAYED: age > max_age (Kritik değilse veya fallback aktifse)
        - STALE_HALT: age > max_age ve veri KRİTİK -> karar kilidi
        """
        now = current_time or datetime.now(timezone.utc)
        rule = self.sla_rules.get(category, {"max_age_seconds": 300, "critical": True})
        max_age = rule["max_age_seconds"]
        is_critical = rule.get("critical", True)

        try:
            as_of_dt = datetime.fromisoformat(as_of_timestamp.replace("Z", "+00:00"))
            age_seconds = max(0.0, (now - as_of_dt).total_seconds())
        except Exception:
            age_seconds = 999999.0

        is_stale = age_seconds > max_age

        if not is_stale:
            status = "FRESH"
            confidence = "NORMAL"
            ui_label = "Tam veri"
            allow_decision = True
        elif not is_critical:
            status = "DELAYED"
            confidence = "PARTIAL_CONFIDENCE"
            ui_label = "Gecikmeli veri (Kritik Olmayan)"
            allow_decision = True  # Bilanço/makro gecikmesinde hisse alım/satımı durmaz
        else:
            status = "STALE_HALT"
            confidence = "LOW"
            ui_label = "Gecikmeli veri (Kritik Kilit)"
            allow_decision = False  # Fiyat/Funding gecikmesinde yeni karar üretilmez

        return {
            "category": category,
            "age_seconds": round(age_seconds, 1),
            "max_age_seconds": max_age,
            "is_critical": is_critical,
            "is_stale": is_stale,
            "status": status,
            "confidence": confidence,
            "ui_label": ui_label,
            "allow_decision": allow_decision
        }


# ════════════════════════════════════════════════════════════════════
# 2. RETRY ENGINE (ÜSTEL GERİ ÇEKİLME VE FALLBACK)
# ════════════════════════════════════════════════════════════════════

class ResilientRetryEngine:
    """Ağ aksaklıklarında 3 kez üstel gecikmeyle (backoff) tekrar dener."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or load_sla_config()
        self.policy = self.config.get("retry_policy", {})
        self.max_retries = self.policy.get("max_retries", 3)
        self.initial_delay_ms = self.policy.get("initial_delay_ms", 300)
        self.multiplier = self.policy.get("backoff_multiplier", 1.5)

    def execute_with_retry(
        self,
        fetch_fn: Callable[[], Any],
        source_name: str = "unknown"
    ) -> Tuple[bool, Any, List[str]]:
        attempts = 0
        errors = []
        delay = self.initial_delay_ms / 1000.0

        while attempts < self.max_retries:
            attempts += 1
            try:
                result = fetch_fn()
                if result is not None:
                    return True, result, errors
                errors.append(f"Deneme {attempts}: Boş yanıt döndü.")
            except Exception as e:
                errors.append(f"Deneme {attempts}: {str(e)}")

            if attempts < self.max_retries:
                time.sleep(delay)
                delay *= self.multiplier

        return False, None, errors


# ════════════════════════════════════════════════════════════════════
# 3. KAYNAK SAĞLIK SKORU VE DEVRE KESİCİ (CIRCUIT BREAKER)
# ════════════════════════════════════════════════════════════════════

class ProviderHealthMonitor:
    """Borsa ve veri sağlayıcılarının arıza oranını takip eden devre kesici."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or load_sla_config()
        self.cb_cfg = self.config.get("circuit_breaker", {})
        self.failure_threshold = self.cb_cfg.get("failure_threshold", 3)
        self.recovery_seconds = self.cb_cfg.get("recovery_time_seconds", 60)
        self.providers: Dict[str, Dict[str, Any]] = {}

    def record_attempt(self, provider: str, success: bool, latency_ms: float = 100.0):
        prov = provider.upper()
        now = time.time()
        if prov not in self.providers:
            self.providers[prov] = {
                "consecutive_failures": 0,
                "total_calls": 0,
                "total_failures": 0,
                "status": "HEALTHY",
                "last_failure_time": 0.0,
                "last_success_time": 0.0,
                "avg_latency_ms": latency_ms
            }

        data = self.providers[prov]
        data["total_calls"] += 1

        if success:
            data["consecutive_failures"] = 0
            data["last_success_time"] = now
            if data["status"] == "DOWN" and (now - data["last_failure_time"]) > self.recovery_seconds:
                data["status"] = "HEALTHY"
            elif data["status"] == "DEGRADED":
                data["status"] = "HEALTHY"
        else:
            data["consecutive_failures"] += 1
            data["total_failures"] += 1
            data["last_failure_time"] = now

            if data["consecutive_failures"] >= self.failure_threshold:
                data["status"] = "DOWN"
            elif data["total_failures"] / float(data["total_calls"]) > 0.25:
                data["status"] = "DEGRADED"

        # Log kaydı
        try:
            event = {
                "provider": prov,
                "status": data["status"],
                "success": success,
                "latency_ms": latency_ms,
                "consecutive_failures": data["consecutive_failures"],
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            with open(HEALTH_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(event) + "\n")
        except Exception:
            pass

    def get_status(self, provider: str) -> str:
        prov = provider.upper()
        data = self.providers.get(prov)
        if not data:
            return "HEALTHY"
        # Otomatik toparlanma süresi kontrolü
        if data["status"] == "DOWN" and (time.time() - data["last_failure_time"]) > self.recovery_seconds:
            data["status"] = "DEGRADED"
        return data["status"]


# Global Tekil Nesneler
GLOBAL_SLA_MANAGER = FreshnessSLAManager()
GLOBAL_RETRY_ENGINE = ResilientRetryEngine()
GLOBAL_HEALTH_MONITOR = ProviderHealthMonitor()
