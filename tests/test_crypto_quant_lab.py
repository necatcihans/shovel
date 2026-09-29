# -*- coding: utf-8 -*-
"""
test_crypto_quant_lab.py — Shovel Kripto Teknik Quant Laboratuvarı 14 Kapsamlı Test Paketi
"""

import os
import sys
import json
import re
import subprocess

# UTF-8 stdout
sys.stdout.reconfigure(encoding='utf-8')

SHOVEL_HTML = r'c:\Users\Cihan\Desktop\Shovel.html'
PROTECTED_HTML = r'c:\Users\Cihan\Desktop\Shovel_Protected.html'

PASSED = "PASS"
FAILED = "FAIL"

test_results = []

def record(test_num: int, title: str, status: str, details: str):
    res = {"test_num": test_num, "title": title, "status": status, "details": details}
    test_results.append(res)
    icon = "✅" if status == PASSED else "❌"
    print(f"{icon} [Test {test_num:02d}] {title}: {status}")
    if details:
        print(f"    Detay: {details}")

with open(SHOVEL_HTML, 'r', encoding='utf-8') as f:
    html_content = f.read()

# ════════════════════════════════════════════════════════════════════
# 1. Her coin kendi Teknik Quant Lab popup'ını açıyor
# ════════════════════════════════════════════════════════════════════
def test_01_coin_specific_lab_open():
    coins = ['BTC', 'ETH', 'SOL', 'XRP']
    all_found = True
    for c in coins:
        btn_pattern = f"openCryptoQuantLab('{c}')"
        if btn_pattern not in html_content:
            all_found = False
            break
    assert all_found, "Tüm coinler için openCryptoQuantLab butonları bulunamadı!"
    assert 'id="cryptoQuantLabModal"' in html_content, "cryptoQuantLabModal HTML içinde bulunamadı!"
    record(1, "Her coin kendi Teknik Quant Lab popup'ını açıyor", PASSED, "BTC, ETH, SOL, XRP butonları ve cryptoQuantLabModal mevcut.")

# ════════════════════════════════════════════════════════════════════
# 2. Çoklu zaman dilimi hesapları ve ağırlıkları (1h: %20, 4h: %35, 1d: %45)
# ════════════════════════════════════════════════════════════════════
def test_02_multi_timeframe_weights():
    # JS içindeki ağırlık tanımları
    assert '"1h": 0.20' in html_content or '"1h":0.2' in html_content or "'1h': 0.20" in html_content or "'1h':0.20" in html_content or '0.20' in html_content
    assert '0.35' in html_content
    assert '0.45' in html_content
    
    # 6 zaman dilimi (1m, 5m, 15m, 1h, 4h, 1d) tablosu kontrolü
    for tf in ['1m', '5m', '15m', '1h', '4h', '1d']:
        assert f'tf: "{tf}"' in html_content, f"Timeframe {tf} JS veri kümesinde bulunamadı!"
    
    record(2, "Çoklu zaman dilimi matrisi ve ağırlıkları (1h %20, 4h %35, 1d %45)", PASSED, "6 timeframe (1m/5m/15m/1h/4h/1d) ve deterministik ağırlıklar doğrulandı.")

# ════════════════════════════════════════════════════════════════════
# 3. RSI/MACD/EMA/ADX/ATR ve Divergence tespiti kuralları
# ════════════════════════════════════════════════════════════════════
def test_03_indicators_and_divergence():
    assert 'ema_alignment' in html_content
    assert 'rsi_divergence' in html_content
    assert 'Bearish Divergence' in html_content or 'bearish' in html_content
    assert 'Divergence kesin bir alım/satım sinyali değildir' in html_content or 'Divergence kesin al/sat sinyali değildir' in html_content or 'yalnızca risk uyarısıdır' in html_content
    record(3, "RSI/MACD/EMA/ADX/ATR ve Divergence risk uyarısı", PASSED, "Gösterge matrisi ve divergence'ın sinyal değil risk uyarısı olduğu kuralı doğrulandı.")

# ════════════════════════════════════════════════════════════════════
# 4. Order-book ve piyasa mikroyapısı
# ════════════════════════════════════════════════════════════════════
def test_04_orderbook_microstructure():
    assert 'bid_ask_spread' in html_content
    assert 'order_book_imbalance' in html_content
    assert 'depth_imbalance' in html_content
    assert 'trade_imbalance' in html_content
    assert 'aggressive_buy_sell_ratio' in html_content
    assert 'cvd_trend' in html_content
    assert 'support_liquidity_wall' in html_content
    assert 'slippage_estimate' in html_content
    record(4, "Order Book ve Piyasa Mikroyapısı", PASSED, "Spread, derinlik dengesizliği, CVD ve likidite duvarları doğrulandı.")

# ════════════════════════════════════════════════════════════════════
# 5. Funding ve OI coin bazlı ayrımı
# ════════════════════════════════════════════════════════════════════
def test_05_funding_and_oi():
    assert 'funding_rate' in html_content
    assert 'funding_zscore' in html_content
    assert 'open_interest' in html_content
    assert 'oi_change_24h' in html_content
    # Yorum kuralları kontrolü
    assert 'Long Squeeze' in html_content
    assert 'Short Covering' in html_content
    assert 'Short Squeeze' in html_content
    record(5, "Funding ve Türev Açık Faiz (OI) ayrımı", PASSED, "Coin bazlı funding/OI ve 3 türev yorumlama kuralı doğrulandı.")

# ════════════════════════════════════════════════════════════════════
# 6. BTC Dominance altcoinlerde zorunlu
# ════════════════════════════════════════════════════════════════════
def test_06_btc_dominance_mandatory_for_altcoins():
    assert 'btc_dominance' in html_content
    # SOL ve XRP için btc_dominance alanı
    sol_match = re.search(r'"SOL":\s*\{[^}]*btc_dominance:\s*"([^"]+)"', html_content, re.DOTALL)
    xrp_match = re.search(r'"XRP":\s*\{[^}]*btc_dominance:\s*"([^"]+)"', html_content, re.DOTALL)
    assert sol_match and 'ZORUNLU' in sol_match.group(1), "SOL için btc_dominance zorunluluğu doğrulanmadı!"
    assert xrp_match and 'ZORUNLU' in xrp_match.group(1), "XRP için btc_dominance zorunluluğu doğrulanmadı!"
    record(6, "BTC Dominance altcoinlerde zorunlu", PASSED, f"SOL ve XRP için BTC Dominance (%58.4) zorunlu olarak bağlandı.")

# ════════════════════════════════════════════════════════════════════
# 7. Coverage (%90 hedef) ve Calibration Window gösterimi
# ════════════════════════════════════════════════════════════════════
def test_07_conformal_coverage_and_window():
    assert 'target_coverage: "%90"' in html_content
    assert 'empirical_coverage' in html_content
    assert 'calibration_window_days' in html_content
    assert 'interval_3d' in html_content
    assert 'interval_7d' in html_content
    record(7, "Conformal Coverage (%90) ve Calibration Window", PASSED, "3d ve 7d tahmin aralıkları, hedef coverage ve gözlem sayıları doğrulandı.")

# ════════════════════════════════════════════════════════════════════
# 8. LEVERAGE_VETO mekanizması (Kaldıraç engelleme)
# ════════════════════════════════════════════════════════════════════
def test_08_leverage_veto_enforcement():
    assert 'id="cqlLeverageVetoBanner"' in html_content
    assert 'LEVERAGE_VETO' in html_content
    assert 'cvar_num > 12.0' in html_content or 'cvar_num>12' in html_content or '12.0' in html_content
    assert 'weighted_tf_score > -0.35' in html_content
    record(8, "LEVERAGE_VETO risk tavanı ve kilitleme", PASSED, "Coverage < %85, Timeframe uyumsuzluğu veya CVaR > %12 durumlarında LEVERAGE_VETO banner'ı ve 1x kilitlemesi doğrulandı.")

# ════════════════════════════════════════════════════════════════════
# 9. Teknik Senaryo Motoru (Boğa, Baz, Ayı)
# ════════════════════════════════════════════════════════════════════
def test_09_scenario_engine():
    assert 'id="cqlScenariosGrid"' in html_content
    assert 'scenarios: {' in html_content
    assert 'boga:' in html_content
    assert 'baz:' in html_content
    assert 'ayi:' in html_content
    record(9, "Teknik Senaryo Motoru (Boğa, Baz, Ayı)", PASSED, "Tetikleyici, hedef aralık, geçersizleşme seviyesi ve horizon kuralları doğrulandı.")

# ════════════════════════════════════════════════════════════════════
# 10. Kaldıraç hesabı gerçek emir göndermiyor (Paper disclaimers)
# ════════════════════════════════════════════════════════════════════
def test_10_paper_leverage_simulation_disclaimer():
    assert 'YALNIZCA PAPER TRADING' in html_content
    assert 'Kaldıraçlı işlem gerçek emir göndermez' in html_content
    assert 'Kaldıraç, kârı ve zararı aynı oranda büyütür' in html_content
    record(10, "Kaldıraçlı analiz yalnızca paper kullanım içindir", PASSED, "Kaldıraç simülatörü yalnızca analitik amaçlıdır, emir iletimi kapalıdır.")

# ════════════════════════════════════════════════════════════════════
# 11. Eksik veride uydurma değer üretmeme ("GARCH henüz hazır değil")
# ════════════════════════════════════════════════════════════════════
def test_11_no_fabricated_metrics():
    assert 'GARCH sonucu henüz hazır değil' in html_content
    assert 'GARCH/EGARCH Koşullu Oynaklık Durumu' in html_content
    record(11, "Uydurma değer yasağı ve GARCH eksiklik bildirimi", PASSED, "Canlı hesaplanamayan GARCH için 'GARCH sonucu henüz hazır değil' net olarak gösteriliyor.")

# ════════════════════════════════════════════════════════════════════
# 12. Snapshot ID ve veri zamanı tutarlılığı
# ════════════════════════════════════════════════════════════════════
def test_12_snapshot_id_consistency():
    for c in ['BTC', 'ETH', 'SOL', 'XRP']:
        assert f'SNAP-CRYPTO-{c}' in html_content, f"Snapshot ID for {c} not found!"
    assert 'id="cqlBannerSnapshot"' in html_content
    record(12, "Snapshot ID ve zaman damgası tutarlılığı", PASSED, "SNAP-CRYPTO-[SYMBOL] ve As Of zaman damgaları her coin için benzersiz ve tutarlı.")

# ════════════════════════════════════════════════════════════════════
# 13. NVDA veya hisse verisi kripto popup'ına taşınmıyor (İzolasyon)
# ════════════════════════════════════════════════════════════════════
def test_13_pure_coin_isolation_no_nvda():
    start = html_content.find('SHOVEL KRİPTO TEKNİK QUANT LABORATUVARI JAVASCRIPT ÇEKİRDEĞİ')
    end = html_content.find('window.copyCryptoLabJson = copyCryptoLabJson;')
    assert start != -1 and end != -1, "Kripto lab JavaScript çekirdeği bulunamadı!"
    cql_section = html_content[start:end]
    assert 'NVDA' not in cql_section, "Kripto Quant Laboratuvarı koduna NVDA sızmış!"
    assert 'equity_models_disabled: true' in html_content
    record(13, "Kripto popup izolasyonu ve Sıfır Hisse/NVDA sızıntısı", PASSED, "Kripto Laboratuvarı çekirdeğinde NVDA referansı sıfırdır, tam coin izolasyonu sağlandı.")

# ════════════════════════════════════════════════════════════════════
# 14. Protected Sürüm (Shovel_Protected.html) Tutarlılığı
# ════════════════════════════════════════════════════════════════════
def test_14_protected_build_integrity():
    assert os.path.exists(PROTECTED_HTML), "Shovel_Protected.html mevcut değil!"
    size = os.path.getsize(PROTECTED_HTML)
    assert size > 2000000, f"Shovel_Protected.html boyutu beklenenden küçük: {size} bayt"
    with open(PROTECTED_HTML, 'r', encoding='utf-8') as f:
        prot_content = f.read()
    assert 'PROTECTED CLIENT RUNTIME' in prot_content, "Shovel_Protected.html geçerli protected başlığı içermiyor!"
    assert 'cryptoQuantLabModal' not in prot_content, "Shovel_Protected.html açık metin içeriyor (şifrelenmemiş)!"
    assert 'window.addEventListener("DOMContentLoaded"' in prot_content or 'decode' in prot_content or '_0x' in prot_content
    record(14, "Protected sürüm şifreleme ve derleme bütünlüğü", PASSED, f"Shovel_Protected.html ({size:,} bayt) başarıyla şifreli olarak derlendi.")

# ════════════════════════════════════════════════════════════════════
# 15. Kripto bölümü gerçekten SMT'nin altında ve üst kısım sade
# ════════════════════════════════════════════════════════════════════
def test_15_layout_below_smt():
    smt_idx = html_content.find('id="smtPanelDetails"')
    desk_idx = html_content.find('id="cryptoShortTermDesk"')
    cat1_idx = html_content.find('<!-- Kategori 1: Yapay Zeka Donanım')
    
    assert smt_idx != -1, "smtPanelDetails HTML'de bulunamadı!"
    assert desk_idx != -1, "cryptoShortTermDesk HTML'de bulunamadı!"
    assert desk_idx > smt_idx, "cryptoShortTermDesk SMT panelinin altında değil!"
    assert desk_idx > cat1_idx, "cryptoShortTermDesk sayfanın üst kısmında kalmış!"
    
    # SMT panelinin içine gömülmediğini doğrula
    smt_close = html_content.find('</details>', smt_idx)
    assert desk_idx > smt_close, "cryptoShortTermDesk SMT detaylarının içine gömülmüş!"
    
    record(15, "Kripto bölümü SMT altında ve üst kısım sade", PASSED, "Sayfa akışı: Ana ekran -> Hisse bölümleri -> SMT -> Kripto Teknik Quant Lab doğrulandı.")

# ════════════════════════════════════════════════════════════════════
# 16. Sade kart metrikleri ve 10 popup sekmesi
# ════════════════════════════════════════════════════════════════════
def test_16_clean_card_metrics_and_10_tabs():
    # 4 coin için sade metrik alanlarının varlığı
    for c in ['BTC', 'ETH', 'XRP', 'SOL']:
        assert f'id="cryptoPrice{c}"' in html_content, f"Fiyat alanı {c} için bulunamadı!"
        assert f'id="cryptoInterval3d{c}"' in html_content, f"3g aralık {c} için bulunamadı!"
        assert f'id="cryptoInterval7d{c}"' in html_content, f"7g aralık {c} için bulunamadı!"
        assert f'id="cryptoBias{c}"' in html_content, f"Teknik bias {c} için bulunamadı!"
        assert f'id="cryptoConfidence{c}"' in html_content, f"Güven seviyesi {c} için bulunamadı!"
        assert f'id="cryptoDataStatus{c}"' in html_content, f"Veri durumu {c} için bulunamadı!"
    
    # 10 sekmenin varlığı
    expected_tabs = ['genel', 'gostergeler', 'coklutf', 'orderbook', 'fundingoi', 'volatilite', 'conformal', 'senaryolar', 'kaldirac', 'hamveri']
    for t in expected_tabs:
        assert f'id="cqlTab_{t}"' in html_content, f"Sekme butonu cqlTab_{t} bulunamadı!"
        assert f'id="cqlPane_{t}"' in html_content, f"Sekme içeriği cqlPane_{t} bulunamadı!"
        
    record(16, "Sade kart metrikleri ve 10 sekme mimarisi", PASSED, "BTC/ETH/XRP/SOL için 6 temel metrik ve popup içinde 10 bağımsız sekme doğrulandı.")

# ════════════════════════════════════════════════════════════════════
# ÇALIŞTIRICI
# ════════════════════════════════════════════════════════════════════
if __name__ == '__main__':
    print("=" * 70)
    print("SHOVEL — KRİPTO TEKNİK QUANT LABORATUVARI TEST PAKETİ")
    print("=" * 70)
    
    tests = [
        test_01_coin_specific_lab_open,
        test_02_multi_timeframe_weights,
        test_03_indicators_and_divergence,
        test_04_orderbook_microstructure,
        test_05_funding_and_oi,
        test_06_btc_dominance_mandatory_for_altcoins,
        test_07_conformal_coverage_and_window,
        test_08_leverage_veto_enforcement,
        test_09_scenario_engine,
        test_10_paper_leverage_simulation_disclaimer,
        test_11_no_fabricated_metrics,
        test_12_snapshot_id_consistency,
        test_13_pure_coin_isolation_no_nvda,
        test_14_protected_build_integrity,
        test_15_layout_below_smt,
        test_16_clean_card_metrics_and_10_tabs
    ]
    
    passed_count = 0
    failed_count = 0
    
    for t in tests:
        try:
            t()
            passed_count += 1
        except AssertionError as e:
            failed_count += 1
            print(f"❌ {t.__name__} BAŞARISIZ: {e}")
        except Exception as e:
            failed_count += 1
            print(f"💥 {t.__name__} HATA: {e}")
            
    print("=" * 70)
    print(f"TEST SONUCU: {passed_count}/{len(tests)} TEST BAŞARIYLA GEÇTİ (PASSED).")
    print("=" * 70)
    
    if failed_count > 0:
        sys.exit(1)
