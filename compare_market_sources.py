# -*- coding: utf-8 -*-
"""
compare_market_sources.py — Shovel Çoklu Kaynak Çapraz Karşılaştırma ve Tolerans Doğrulama Aracı

İşlevler:
1. Birincil ve ikincil kaynaklar arasındaki farkı kalibre edilmiş toleranslara göre kıyaslar.
2. Spot/Futures, farklı vade ayları ve contango/backwardation durumlarını denetler.
3. 3 kaynak uyuşmazlığında DATA_VALIDATION_FAILED kuralının doğru çalıştığını test eder.
4. Tek kaynaklı resmi verilerin (VIX, M2, FED_RATE) reddedilmediğini teyit eder.
"""

from __future__ import annotations

import os
import sys
import json
from pathlib import Path
from typing import Dict, Any, List

# UTF-8 stdout
try:
    if hasattr(sys.stdout, 'reconfigure') and not sys.stdout.closed:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE_DIR = Path(__file__).resolve().parent
CONFIG_DIR = BASE_DIR / "config"

from shovel_asset_resolver import (
    CanonicalAssetRegistry,
    cross_validate_sources,
    CalibratedToleranceManager,
    ContractCompatibilityChecker,
    MultiSourceValidator
)


def run_source_comparisons() -> int:
    print("=" * 70)
    print("SHOVEL — ÇOKLU KAYNAK VE VADE DOĞRULAMA DENETİMİ (CI)")
    print("=" * 70)

    registry = CanonicalAssetRegistry()
    failures = []

    # 1. TEST: Brent Ham Petrol Kontrat / Vade Uyumsuzluğu
    brent_def = registry.resolve_canonical("BRENT")
    p_meta_oct = {"instrument_type": "futures", "contract_month": "2026-10", "curve_state": "backwardation"}
    s_meta_dec = {"instrument_type": "futures", "contract_month": "2026-12", "curve_state": "backwardation"}
    
    res_vade = cross_validate_sources(
        canonical_symbol="BRENT",
        asset_class="commodity",
        primary_price=82.50,
        secondary_price=80.10,
        primary_contract_meta=p_meta_oct,
        secondary_contract_meta=s_meta_dec,
        asset_def=brent_def
    )
    if res_vade["status"] != "CONTRACT_MISMATCH":
        failures.append(f"BRENT farklı vade ayı CONTRACT_MISMATCH vermedi! (Verilen: {res_vade['status']})")
    elif res_vade["is_conflict"] is not False:
        failures.append("BRENT vade farkı yanlışlıkla SOURCE_CONFLICT sayıldı!")
    else:
        print("  ✓ [Kontrat/Vade Testi] BRENT Oct vs Dec: CONTRACT_MISMATCH doğru üretildi, sahte hata elendi.")

    # 2. TEST: Spot vs Futures Uyuşmazlığı (Brent Spot vs Brent Vadeli)
    p_meta_spot = {"instrument_type": "spot", "contract_month": "spot", "curve_state": "flat"}
    s_meta_fut = {"instrument_type": "futures", "contract_month": "front_month", "curve_state": "contango"}
    res_spot_fut = cross_validate_sources(
        canonical_symbol="BRENT",
        asset_class="commodity",
        primary_price=82.00,
        secondary_price=84.50,
        primary_contract_meta=p_meta_spot,
        secondary_contract_meta=s_meta_fut,
        asset_def=brent_def
    )
    if res_spot_fut["status"] != "CONTRACT_MISMATCH":
        failures.append(f"Spot vs Futures CONTRACT_MISMATCH vermedi! (Verilen: {res_spot_fut['status']})")
    else:
        print("  ✓ [Spot vs Futures Testi] Spot vs Vadeli ayrımı başarıyla CONTRACT_MISMATCH üretti.")

    # 3. TEST: Kalibre Edilmiş Tolerans İçi Kabul (Örn: NVDA %0.5 fark, tolerans %1.0)
    res_nvda_ok = cross_validate_sources(
        canonical_symbol="NVDA",
        asset_class="us_equity",
        primary_price=125.00,
        secondary_price=125.60
    )
    if res_nvda_ok["status"] != "PASS":
        failures.append(f"NVDA tolerans içi fark PASS almadı! (Verilen: {res_nvda_ok['status']})")
    else:
        print("  ✓ [Kalibre Tolerans Testi] NVDA %0.48 fark: PASS olarak kabul edildi.")

    # 4. TEST: Kalibre Edilmiş Tolerans Dışı Çatışma (Örn: USDTRY %1.2 fark, tolerans %0.5)
    res_try_conflict = cross_validate_sources(
        canonical_symbol="USDTRY",
        asset_class="fx",
        primary_price=34.00,
        secondary_price=34.50
    )
    if res_try_conflict["status"] != "SOURCE_CONFLICT":
        failures.append(f"USDTRY aşırı fark SOURCE_CONFLICT vermedi! (Verilen: {res_try_conflict['status']})")
    else:
        print("  ✓ [Tolerans Aşımı Testi] USDTRY %1.46 fark: SOURCE_CONFLICT doğru tetiklendi.")

    # 5. TEST: 3 Kaynak Çelişkisi ve DATA_VALIDATION_FAILED
    three_divergent_quotes = [
        {"symbol": "BRENT", "asset_class": "commodity", "instrument_type": "futures", "contract_month": "front_month", "currency": "USD", "unit": "barrel", "price": 80.00, "source": "ice", "as_of": "2026-09-28T12:00:00Z"},
        {"symbol": "BRENT", "asset_class": "commodity", "instrument_type": "futures", "contract_month": "front_month", "currency": "USD", "unit": "barrel", "price": 85.00, "source": "yahoo", "as_of": "2026-09-28T12:00:00Z"},
        {"symbol": "BRENT", "asset_class": "commodity", "instrument_type": "futures", "contract_month": "front_month", "currency": "USD", "unit": "barrel", "price": 92.00, "source": "tradingview", "as_of": "2026-09-28T12:00:00Z"}
    ]
    three_res = MultiSourceValidator.validate_three_or_more_sources(brent_def, three_divergent_quotes)
    if three_res["status"] != "DATA_VALIDATION_FAILED":
        failures.append(f"3 kaynak uyuşmazlığında DATA_VALIDATION_FAILED üretilmedi! (Verilen: {three_res['status']})")
    else:
        print("  ✓ [3-Kaynak Uyuşmazlığı Testi] DATA_VALIDATION_FAILED başarıyla tetiklendi.")

    # 6. TEST: Tek Kaynaklı Varlık Güvencesi (VIX)
    vix_def = registry.resolve_canonical("VIX")
    if not vix_def or not vix_def.single_authoritative_source:
        failures.append("VIX varlığı single_authoritative_source olarak tanımlı değil!")
    else:
        print("  ✓ [Tek Kaynak Güvencesi] VIX resmi tekil kaynak olarak tescil edildi.")

    print("-" * 70)
    if failures:
        print("❌ KAYNAK KARŞILAŞTIRMA TESTLERİNDE HATA BULUNDU:")
        for f in failures:
            print(f"  • {f}")
        print("=" * 70)
        return 1

    print("✅ TÜM KAYNAK VE VADE KARŞILAŞTIRMALARI BAŞARIYLA TAMAMLANDI (PASS).")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(run_source_comparisons())
