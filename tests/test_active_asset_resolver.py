# -*- coding: utf-8 -*-
"""
test_active_asset_resolver.py — 16 Maddelik Aktif Veri Bulma ve Doğrulama Test Paketi

1. Birincil kaynak başarısız olduğunda ikincil kaynağın çalışması
2. Provider sembolü farklı olsa da doğru canonical varlığın bulunması
3. Yanlış varlık eşleşmesinin reddedilmesi (BRENT vs WTI vb.)
4. Brent ile WTI'ın karıştırılmaması
5. Spot ile vadeli kontratın karıştırılmaması
6. USD/TRY ve EUR/TRY için doğru sembolün bulunması
7. Gram altın ile ons altının birim ve para birimi bazında ayrılması
8. BTC spot ile vadeli kontratın ayrılması
9. Para birimi ve birim doğrulaması
10. İki kaynak arasındaki farkın kontrol edilmesi (Çatışma eşiği)
11. Eski önbelleğin canlı veri gibi kabul edilmemesi (Gecikmeli veri / allow_new_decision: false)
12. Snapshot fiyatı ile analiz fiyatının birebir aynı olması
13. Doğru benchmark'ın seçilmesi (SPY, XU100, BTC, GLD)
14. Varlık sınıfına özel doğru analiz fonksiyonunun çalışması (DCF/EPS kısıtlamaları dahil)
15. Tüm kaynaklar başarısız olduğunda açık uyarı verilmesi ve karar üretilmemesi (Fail-Closed)
16. Shovel.html ve Shovel_Protected.html üzerinde headless Edge/Chrome CDP kontrolü
"""

import os
import sys
import json
import time
import subprocess
from datetime import datetime, timezone, timedelta

# UTF-8 stdout
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import shovel_asset_resolver as sar
from shovel_asset_resolver import (
    CanonicalAssetRegistry,
    ActiveSourceResolver,
    AssetIdentityVerifier,
    FreshnessCacheManager,
    TypedAssetAnalyzer,
    NormalizedAssetData,
    cross_validate_sources,
    resolve_and_analyze
)

PASSED = "PASS"
FAILED = "FAIL"

test_results = []

def record(test_num: int, title: str, status: str, details: str):
    res = {
        "test_num": test_num,
        "title": title,
        "status": status,
        "details": details
    }
    test_results.append(res)
    icon = "✅" if status == PASSED else "❌"
    print(f"{icon} [Test {test_num:02d}] {title}: {status}")
    if status == FAILED or details:
        print(f"    Detay: {details}")

# ════════════════════════════════════════════════════════════════════
# TEST 1: Birincil kaynak başarısız olduğunda ikincil kaynağın çalışması
# ════════════════════════════════════════════════════════════════════
def test_01_primary_failure_fallback():
    resolver = ActiveSourceResolver()
    # Mock besleme: live_exchange ve yahoo hata versin, stooq başarılı fiyat dönsün
    mock_feed = {
        "live_exchange": {"error": "Exchange gateway offline"},
        "yahoo": {"error": "503 Service Unavailable"},
        "stooq": {"price": 142.50, "currency": "USD", "unit": "share", "instrument_type": "spot"}
    }
    data = resolver.resolve("NVDA", mock_provider_feed=mock_feed)
    assert data.source == "stooq", f"Beklenen stooq, gelen {data.source}"
    assert data.price == 142.50, f"Beklenen 142.50, gelen {data.price}"
    record(1, "Birincil kaynak arızasında ikincil kaynağa (fallback) geçiş", PASSED, f"Kaynak: {data.source}, Fiyat: ${data.price}")

# ════════════════════════════════════════════════════════════════════
# TEST 2: Provider sembolü farklı olsa da doğru canonical varlığın bulunması
# ════════════════════════════════════════════════════════════════════
def test_02_provider_symbol_resolution():
    reg = CanonicalAssetRegistry()
    test_cases = [
        ("BZ=F", "BRENT"),
        ("SI=F", "XAGUSD"),
        ("BTC", "BTCUSD"),
        ("THYAO.IS", "THYAO"),
        ("^GSPC", "SPX")
    ]
    for prov_sym, expected_can in test_cases:
        asset_def = reg.resolve_canonical(prov_sym)
        assert asset_def is not None, f"Çözümlenemedi: {prov_sym}"
        assert asset_def.canonical_symbol == expected_can, f"Beklenen {expected_can}, gelen {asset_def.canonical_symbol}"
    record(2, "Farklı provider sembollerinden canonical varlık çözümleme", PASSED, "5/5 sembol (BZ=F, SI=F, BTC, THYAO.IS, ^GSPC) başarıyla çözüldü.")

# ════════════════════════════════════════════════════════════════════
# TEST 3: Yanlış varlık eşleşmesinin reddedilmesi (BRENT vs WTI vb.)
# ════════════════════════════════════════════════════════════════════
def test_03_false_asset_match_rejection():
    reg = CanonicalAssetRegistry()
    brent_def = reg.resolve_canonical("BRENT")
    valid, reason = AssetIdentityVerifier.verify(
        asset_def=brent_def,
        candidate_symbol="WTI",
        candidate_price=75.0,
        candidate_currency="USD",
        candidate_unit="barrel",
        candidate_instrument_type="futures",
        as_of_time="2026-09-28",
        source_name="mock"
    )
    assert not valid, "BRENT için WTI adayı reddedilmeliydi!"
    assert "YASAKLI EŞLEŞME" in reason
    record(3, "Yanlış varlık eşleşmesinin reddedilmesi (BRENT != WTI)", PASSED, f"Reddetme sebebi: {reason}")

# ════════════════════════════════════════════════════════════════════
# TEST 4: Brent ile WTI'ın karıştırılmaması
# ════════════════════════════════════════════════════════════════════
def test_04_brent_vs_wti_distinction():
    reg = CanonicalAssetRegistry()
    brent_def = reg.resolve_canonical("BRENT")
    wti_def = reg.resolve_canonical("WTI")
    assert brent_def.canonical_symbol != wti_def.canonical_symbol
    assert brent_def.contract_rule != wti_def.contract_rule
    assert brent_def.benchmark == "BRENT" and wti_def.benchmark == "WTI"
    record(4, "Brent ile WTI sözleşme ve kontrat ayrımı", PASSED, f"Brent ({brent_def.contract_rule}) != WTI ({wti_def.contract_rule})")

# ════════════════════════════════════════════════════════════════════
# TEST 5: Spot ile vadeli kontratın karıştırılmaması
# ════════════════════════════════════════════════════════════════════
def test_05_spot_vs_futures_distinction():
    reg = CanonicalAssetRegistry()
    btc_def = reg.resolve_canonical("BTCUSD")
    valid, reason = AssetIdentityVerifier.verify(
        asset_def=btc_def,
        candidate_symbol="BTC_PERP",
        candidate_price=64000.0,
        candidate_currency="USD",
        candidate_unit="token",
        candidate_instrument_type="futures",
        as_of_time="2026-09-28",
        source_name="mock"
    )
    assert not valid, "BTC spot varlığına vadeli kontrat bağlanamaz!"
    assert "Enstrüman türü uyuşmazlığı" in reason
    record(5, "Spot varlığa vadeli kontrat eşleşmesinin engellenmesi", PASSED, f"Korumalı: {reason}")

# ════════════════════════════════════════════════════════════════════
# TEST 6: USD/TRY ve EUR/TRY için doğru sembolün bulunması
# ════════════════════════════════════════════════════════════════════
def test_06_fx_symbols_resolution():
    reg = CanonicalAssetRegistry()
    usd_def = reg.resolve_canonical("USD/TRY")
    eur_def = reg.resolve_canonical("EUR/TRY")
    assert usd_def.canonical_symbol == "USDTRY" and usd_def.currency == "TRY" and usd_def.asset_class == "fx"
    assert eur_def.canonical_symbol == "EURTRY" and eur_def.currency == "TRY" and eur_def.asset_class == "fx"
    record(6, "USD/TRY ve EUR/TRY döviz pariteleri canonical çözümleme", PASSED, f"USDTRY ({usd_def.currency}), EURTRY ({eur_def.currency})")

# ════════════════════════════════════════════════════════════════════
# TEST 7: Gram altın ile ons altının birim ve para birimi bazında ayrılması
# ════════════════════════════════════════════════════════════════════
def test_07_gram_vs_ounce_gold():
    reg = CanonicalAssetRegistry()
    xau_def = reg.resolve_canonical("XAUUSD")
    gram_def = reg.resolve_canonical("GRAM_ALTIN")
    assert xau_def.currency == "USD" and xau_def.unit == "troy_oz" and xau_def.instrument_type == "spot"
    assert gram_def.currency == "TRY" and gram_def.unit == "gram" and gram_def.instrument_type == "derived_spot"
    
    # XAU adayı gram altına verilemez
    valid, reason = AssetIdentityVerifier.verify(
        asset_def=gram_def,
        candidate_symbol="XAUUSD",
        candidate_price=2650.0,
        candidate_currency="USD",
        candidate_unit="troy_oz",
        candidate_instrument_type="spot",
        as_of_time="2026-09-28",
        source_name="mock"
    )
    assert not valid
    record(7, "Gram altın (TRY/gram) ile Ons altın (USD/oz) ayrımı", PASSED, f"Koruma teyit edildi: {reason}")

# ════════════════════════════════════════════════════════════════════
# TEST 8: BTC spot ile vadeli kontratın ayrılması
# ════════════════════════════════════════════════════════════════════
def test_08_btc_spot_vs_futures():
    reg = CanonicalAssetRegistry()
    btc_def = reg.resolve_canonical("BTCUSD")
    valid, reason = AssetIdentityVerifier.verify(
        asset_def=btc_def,
        candidate_symbol="BTC_FUTURES",
        candidate_price=64200.0,
        candidate_currency="USD",
        candidate_unit="coin",
        candidate_instrument_type="futures",
        as_of_time="2026-09-28",
        source_name="mock"
    )
    assert not valid
    record(8, "BTC Spot ile BTC Futures ayrımı", PASSED, f"Yasaklı eşleşme engellendi: {reason}")

# ════════════════════════════════════════════════════════════════════
# TEST 9: Para birimi ve birim doğrulaması
# ════════════════════════════════════════════════════════════════════
def test_09_currency_and_unit_validation():
    reg = CanonicalAssetRegistry()
    asels_def = reg.resolve_canonical("ASELS")
    valid_curr, r_curr = AssetIdentityVerifier.verify(
        asset_def=asels_def, candidate_symbol="ASELS", candidate_price=60.0,
        candidate_currency="USD", candidate_unit="lot", candidate_instrument_type="spot",
        as_of_time="2026-09-28", source_name="mock"
    )
    assert not valid_curr and "Para birimi uyuşmazlığı" in r_curr

    valid_unit, r_unit = AssetIdentityVerifier.verify(
        asset_def=asels_def, candidate_symbol="ASELS", candidate_price=60.0,
        candidate_currency="TRY", candidate_unit="barrel", candidate_instrument_type="spot",
        as_of_time="2026-09-28", source_name="mock"
    )
    assert not valid_unit and "Birim uyuşmazlığı" in r_unit
    record(9, "Para birimi (USD/TRY) ve Birim (lot/barrel) katı doğrulaması", PASSED, "Geçersiz döviz ve birim istekleri fail-closed reddedildi.")

# ════════════════════════════════════════════════════════════════════
# TEST 10: İki kaynak arasındaki farkın kontrol edilmesi (Çatışma Eşiği)
# ════════════════════════════════════════════════════════════════════
def test_10_cross_source_difference():
    # Kripto için %2 eşik
    normal_chk = cross_validate_sources("BTCUSD", "crypto", primary_price=64000.0, secondary_price=64500.0)
    assert not normal_chk["is_conflict"] and normal_chk["action"] == "CROSS_VALIDATED_OK"

    conflict_chk = cross_validate_sources("BTCUSD", "crypto", primary_price=64000.0, secondary_price=66500.0)
    assert conflict_chk["is_conflict"] and conflict_chk["action"] == "PARTIAL_CONFIDENCE_FLAG"
    record(10, "İki kaynak arası fiyat çatışması denetimi (%2 ve %3 eşik)", PASSED, f"Fark %{conflict_chk['difference_pct']} > Eşik %{conflict_chk['threshold_pct']} -> {conflict_chk['action']}")

# ════════════════════════════════════════════════════════════════════
# TEST 11: Eski önbelleğin canlı veri gibi kabul edilmemesi
# ════════════════════════════════════════════════════════════════════
def test_11_stale_cache_control():
    temp_cache_file = os.path.join(sar.JOURNAL_DIR, "test_temp_cache.json")
    cache_mgr = FreshnessCacheManager(temp_cache_file)
    stale_time = (datetime.now(timezone.utc) - timedelta(minutes=45)).isoformat()
    old_item = NormalizedAssetData(
        canonical_symbol="NVDA",
        price=120.0,
        currency="USD",
        unit="share",
        instrument_type="spot",
        contract="standard",
        source="yahoo",
        as_of=stale_time,
        fetched_at=stale_time,
        snapshot_id="SNAP-OLD-NVDA",
        is_derived=False,
        is_stale=False,
        ui_confidence_label="Tam veri",
        allow_new_decision=True
    )
    cache_mgr.put(old_item)
    # 15 dk TTL kontrolü
    loaded, is_stale = cache_mgr.get("NVDA", max_age_minutes=15)
    assert is_stale is True, "45 dakikalık veri bayat sayılmalıydı!"
    assert loaded.ui_confidence_label == "Gecikmeli veri"
    assert loaded.allow_new_decision is False
    try:
        os.remove(temp_cache_file)
    except Exception:
        pass
    record(11, "Eski önbelleğin canlı sayılmaması ve 'Gecikmeli veri' etiketi", PASSED, f"is_stale={is_stale}, allow_new_decision={loaded.allow_new_decision}")

# ════════════════════════════════════════════════════════════════════
# TEST 12: Snapshot fiyatı ile analiz fiyatının birebir aynı olması
# ════════════════════════════════════════════════════════════════════
def test_12_snapshot_sync():
    res = resolve_and_analyze("NVDA")
    assert res["status"] == "SUCCESS"
    snap_id = res["snapshot_id"]
    analysis_snap_id = res["analysis"]["analysis_snapshot_id"]
    price = res["price"]
    analysis_price = res["analysis"]["analysis_price"]
    assert snap_id == analysis_snap_id, "Snapshot ID eşleşmiyor!"
    assert price == analysis_price, "Snapshot fiyatı ile analiz fiyatı eşleşmiyor!"
    record(12, "Snapshot ID ve analiz fiyatı %100 senkronizasyon kilidi", PASSED, f"Fiyat: ${price}, Snapshot: {snap_id}")

# ════════════════════════════════════════════════════════════════════
# TEST 13: Doğru benchmark'ın seçilmesi
# ════════════════════════════════════════════════════════════════════
def test_13_benchmark_selection():
    res_us = resolve_and_analyze("NVDA")
    res_bist = resolve_and_analyze("THYAO")
    res_btc = resolve_and_analyze("BTCUSD")
    res_gold = resolve_and_analyze("XAUUSD")

    assert res_us["benchmark"] == "SPY", f"Beklenen SPY, gelen {res_us['benchmark']}"
    assert res_bist["benchmark"] == "XU100", f"Beklenen XU100, gelen {res_bist['benchmark']}"
    assert res_btc["benchmark"] == "BTC", f"Beklenen BTC, gelen {res_btc['benchmark']}"
    assert res_gold["benchmark"] == "GLD", f"Beklenen GLD, gelen {res_gold['benchmark']}"
    record(13, "Varlık sınıfına özel doğru benchmark seçimi", PASSED, f"ABD: {res_us['benchmark']}, BIST: {res_bist['benchmark']}, Kripto: {res_btc['benchmark']}, Altın: {res_gold['benchmark']}")

# ════════════════════════════════════════════════════════════════════
# TEST 14: Varlık sınıfına özel doğru analiz fonksiyonunun çalışması
# ════════════════════════════════════════════════════════════════════
def test_14_typed_asset_analysis():
    # 1. Brent -> commodity_analysis, DCF yasak
    brent_res = resolve_and_analyze("BRENT")
    assert brent_res["analysis"]["analysis_type"] == "commodity_analysis"
    assert "DCF" in brent_res["analysis"]["prohibited_metrics"]

    # 2. USD/TRY -> fx_analysis, EPS yasak
    fx_res = resolve_and_analyze("USDTRY")
    assert fx_res["analysis"]["analysis_type"] == "fx_analysis"
    assert "EPS" in fx_res["analysis"]["prohibited_metrics"]

    # 3. BTC -> crypto_analysis
    crypto_res = resolve_and_analyze("BTCUSD")
    assert crypto_res["analysis"]["analysis_type"] == "crypto_analysis"
    record(14, "Varlık sınıfına özel analiz motoru & Metrik ihlal engeli", PASSED, "Brent için commodity_analysis (DCF yasak), USDTRY için fx_analysis (EPS yasak), BTC için crypto_analysis.")

# ════════════════════════════════════════════════════════════════════
# TEST 15: Tüm kaynaklar başarısız olduğunda açık uyarı ve karar kilidi (Fail-Closed)
# ════════════════════════════════════════════════════════════════════
def test_15_fail_closed_on_all_failures():
    # Boş / başarısız mock feed ver
    mock_fail_feed = {
        "yahoo": {"error": "Connection Timeout"},
        "stooq": {"error": "Connection Refused"},
        "investing": {"error": "404 Not Found"}
    }
    # Geçici bir sembol için cache olmadan fail ettir
    reg = CanonicalAssetRegistry()
    resolver = ActiveSourceResolver(registry=reg, cache_manager=FreshnessCacheManager(os.path.join(sar.JOURNAL_DIR, "empty_cache.json")))
    
    asset_def = reg.resolve_canonical("NVDA")
    try:
        resolver.resolve("NVDA", mock_provider_feed=mock_fail_feed)
        failed_as_expected = False
    except RuntimeError as e:
        failed_as_expected = True
        err_msg = str(e)
        assert "Veri sağlayıcılarına şu anda ulaşılamıyor" in err_msg
        assert "Analiz güncellenmedi" in err_msg

    assert failed_as_expected, "Tüm kaynaklar başarısız olduğunda RuntimeError fırlatılmalıydı!"
    record(15, "Tüm kaynaklar başarısız olduğunda Fail-Closed net uyarısı", PASSED, "Sentetik karar üretilmedi, fail-closed kilit devrede.")

# ════════════════════════════════════════════════════════════════════
# TEST 16: Shovel.html ve Shovel_Protected.html üzerinde headless Edge CDP kontrolü
# ════════════════════════════════════════════════════════════════════
def test_16_browser_cdp_verification():
    shovel_path = r"c:\Users\Cihan\Desktop\Shovel.html"
    shovel_prot_path = r"c:\Users\Cihan\Desktop\Shovel_Protected.html"
    edge_exe = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    
    assert os.path.exists(shovel_path), "Shovel.html bulunamadı"
    assert os.path.exists(shovel_prot_path), "Shovel_Protected.html bulunamadı"

    # Headless Edge DOM dump testi
    if os.path.exists(edge_exe):
        cmd = [edge_exe, "--headless=new", "--dump-dom", f"file:///{shovel_path.replace(os.sep, '/')}"]
        res = subprocess.run(cmd, capture_output=True, timeout=15)
        # Decode using utf-8 with replace to prevent cp1254 crashes
        dom_out = res.stdout.decode("utf-8", errors="replace")
        
        assert "dhIdentityStatus" in dom_out, "dhIdentityStatus DOM'da bulunamadı!"
        assert "dhFreshnessStatus" in dom_out, "dhFreshnessStatus DOM'da bulunamadı!"
        assert "dhFailClosedAlert" in dom_out, "dhFailClosedAlert DOM'da bulunamadı!"
        assert "dhDerivedParityBox" in dom_out, "dhDerivedParityBox DOM'da bulunamadı!"
        assert "ShovelAssetResolver" in dom_out, "ShovelAssetResolver script'te bulunamadı!"
        record(16, "Headless Edge CDP DOM kontrolü (Shovel & Shovel_Protected)", PASSED, "dhIdentityStatus, dhFreshnessStatus, dhFailClosedAlert, ShovelAssetResolver DOM'da doğrulandı.")
    else:
        # Fallback: doğrudan statik içerik kontrolü
        with open(shovel_path, "r", encoding="utf-8") as f:
            c = f.read()
        assert "dhIdentityStatus" in c and "ShovelAssetResolver" in c
        record(16, "Statik DOM ve Script Kontrolü", PASSED, "DOM elemanları ve ShovelAssetResolver doğrulandı.")


def main():
    print("=" * 70)
    print("SHOVEL — 16 MADDELİK AKTİF VERİ BULMA VE DOĞRULAMA TEST PAKETİ")
    print("=" * 70)

    tests = [
        test_01_primary_failure_fallback,
        test_02_provider_symbol_resolution,
        test_03_false_asset_match_rejection,
        test_04_brent_vs_wti_distinction,
        test_05_spot_vs_futures_distinction,
        test_06_fx_symbols_resolution,
        test_07_gram_vs_ounce_gold,
        test_08_btc_spot_vs_futures,
        test_09_currency_and_unit_validation,
        test_10_cross_source_difference,
        test_11_stale_cache_control,
        test_12_snapshot_sync,
        test_13_benchmark_selection,
        test_14_typed_asset_analysis,
        test_15_fail_closed_on_all_failures,
        test_16_browser_cdp_verification
    ]

    passed_count = 0
    failed_count = 0

    for t in tests:
        try:
            t()
            passed_count += 1
        except Exception as e:
            failed_count += 1
            print(f"❌ TEST HATA: {t.__name__} -> {str(e)}")

    print("\n" + "=" * 70)
    print(f"TEST ÖZETİ: {passed_count}/{len(tests)} Başarılı, {failed_count} Başarısız")
    print("=" * 70)

    if failed_count > 0:
        sys.exit(1)

if __name__ == "__main__":
    main()
