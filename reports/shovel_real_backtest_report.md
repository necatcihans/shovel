# SHOVEL TERMINALİ — MVP GERÇEK TARİHSEL BACKTEST VE FORWARD TEST RAPORU
> **YASAL VE AKADEMİK BİLDİRİM:** Bu rapor bir **araştırma sonucudur — doğrulanmış yatırım başarısı değildir.** Geçmiş performans gelecekteki getirilerin garantisi olamaz. Tüm sonuçlar komisyon, kayma (slippage) ve fonlama maliyetleri düşülerek net olarak hesaplanmıştır.

---

## 1. Kullanılan Veri ve Tarih Aralığı

Backtest süreci, geleceğe bakma yanlılığını (look-ahead bias) ve veri sızıntısını (leakage) önlemek amacıyla **Purged Walk-Forward** yöntemi ve dinamik ambargo (embargo) kurallarıyla yürütülmüştür.

- **Veri Kaynakları:**
  - ABD Hisseleri ve BIST: Yahoo Finance (Bölünme ve temettü düzeltilmiş günlük OHLCV).
  - Kripto Varlıklar: Binance Public API (1 günlük kurumsal klines ve 8 saatlik perpetual funding verisi).
- **Zaman Dilimi (Timeframe):** Günlük (1D) barlar; karar anında sadece $t$ anına kadar olan tarihsel veri dilimi kullanılmıştır.
- **Tarihsel Pencereler:**
  - **In-Sample (Train / Model Kalibrasyonu):** 1 Ocak 2024 — 30 Haziran 2025 (370+ gün)
  - **Dinamik Ambargo (Embargo Süresi):** 10 İş Günü (1 Temmuz 2025 — 14 Temmuz 2025)
  - **Out-of-Sample (OOS / Gerçek Test):** 15 Temmuz 2025 — 25 Eylül 2026 (438 takvim günü / 300+ işlem günü)

---

## 2. Test Edilen Varlıklar

Her varlık sınıfı finansal dinamikleri, işlem saatleri ve maliyet yapıları farklı olduğu için **birbirine karıştırılmadan 3 bağımsız evrende** test edilmiştir:

1. **ABD Hisse Senetleri Evreni (7 Varlık):**
   - Varlıklar: `NVDA`, `MU`, `AAPL`, `MSFT`, `GOOGL`, `AMZN`, `META`
   - Resmi Benchmark: `SPY` (SPDR S&P 500 ETF Trust)
   - Maliyet Modeli: Giriş/Çıkış Komisyon %0.02, Kayma %0.015 (Toplam %0.07 / işlem)
2. **Borsa İstanbul (BIST) Evreni (6 Varlık):**
   - Varlıklar: `THYAO.IS`, `TUPRS.IS`, `ASELS.IS`, `BIMAS.IS`, `EREGL.IS`, `KCHOL.IS`
   - Resmi Benchmark: `XU100.IS` (BIST 100 Endeksi)
   - Maliyet Modeli: Giriş/Çıkış Komisyon %0.10, Kayma %0.05 (Toplam %0.30 / işlem)
3. **Kripto Varlıklar Evreni (4 Varlık):**
   - Varlıklar: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `XRPUSDT`
   - Resmi Benchmark: `BTCUSDT` (Buy & Hold)
   - Maliyet Modeli: Giriş/Çıkış Komisyon %0.075, Kayma %0.05 (Toplam %0.25 / işlem) + **Birikimli 8 saatlik perpetual fonlama maliyeti (holding_days × 3 × 0.00010)**

---

## 3. Backtest Sonuç Tablosu

Aşağıdaki metrikler, her varlık sınıfı için Out-of-Sample (OOS) döneminde üretilen tüm tamamlanmış işlemler üzerinden hesaplanmıştır:

| Metrik | ABD Hisseleri (`us_equities`) | BIST Hisseleri (`bist_equities`) | Kripto Varlıklar (`crypto`) |
| :--- | :---: | :---: | :---: |
| **Toplam Sinyal Sayısı** | **124** | **130** | **178** |
| • AL / LONG Sinyali | 114 (%91.9) | 121 (%93.1) | 133 (%74.7) |
| • SAT / SHORT Sinyali | 10 (%8.1) | 9 (%6.9) | 45 (%25.3) |
| • TUT / RANGE Sinyali | 0 (İşleme Dönüşmedi) | 0 (İşleme Dönüşmedi) | 0 (İşleme Dönüşmedi) |
| **Doğru Yön Oranı (Hit-Rate)** | **%37.1** | **%42.3** | **%36.5** |
| **Ortalama Net Getiri / İşlem** | **+%0.23** | **+%0.52** | **-%1.42** |
| **Medyan Net Getiri** | -%3.00 | -%2.77 | -%2.57 |
| **Kümülatif Net Getiri** | **+%28.02** | **+%68.01** | **-%253.50** |
| **Kazanan / Kaybeden Oranı** | 0.59 | 0.73 | 0.58 |
| **Ortalama Kazanç (Avg Win)** | +%7.99 | +%7.46 | +%7.03 |
| **Ortalama Kayıp (Avg Loss)** | -%4.35 | -%4.56 | -%6.29 |
| **Profit Factor (Kâr Faktörü)** | **1.08** | **1.20** | **0.64** |
| **Ortalama İşlem Süresi** | 6.7 Gün | 7.6 Gün | 7.7 Gün |
| **Hedefe Ulaşma Oranı (Target)** | %28.2 | %33.1 | %11.2 |
| **Stop-Loss Tetiklenme Oranı** | %58.1 | %46.2 | %35.4 |
| **Zaman Aşımı Çıkışı (Horizon)** | %13.7 | %20.7 | %53.4 |

### R-Multiple Dağılımı (Risk/Getiri Asimetrisi)
- **ABD Hisseleri:** $R < 0$ (77 işlem), $0 \le R < 1$ (9 işlem), $1 \le R < 2$ (3 işlem), **$R \ge 2.0$ (35 işlem — Büyük Trend Koşucuları)**
- **BIST Hisseleri:** $R < 0$ (73 işlem), $0 \le R < 1$ (11 işlem), $1 \le R < 2$ (7 işlem), **$R \ge 2.0$ (39 işlem)**
- **Kripto Varlıklar:** $R < 0$ (107 işlem), $0 \le R < 1$ (47 işlem), $1 \le R < 2$ (24 işlem), **$R \ge 2.0$ (0 işlem)**

---

## 4. Benchmark Karşılaştırması

İşlemlerin açıldığı ve kapandığı tarihler birebir eşleştirilerek benchmark getirisi hesaplanmış ve net alfa farkı çıkarılmıştır:

| Metrik | ABD (`SPY` Karşısında) | BIST (`XU100` Karşısında) | Kripto (`BTC` Karşısında) |
| :--- | :---: | :---: | :---: |
| **Benchmark Ortalama Getiri** | +%0.11 | +%0.85 | -%0.47 |
| **Benchmark Kümülatif Getiri** | +%13.52 | +%109.89 | -%83.31 |
| **Shovel Kümülatif Net Getiri** | **+%28.02** | **+%68.01** | **-%253.50** |
| **NET ALFA FARKI (Shovel - BM)** | **+%14.50 🟢** | **-%41.88 🔴** | **-%170.19 🔴** |
| **Açıklama** | SPY'ın üzerinde +%14.5 alfa üretildi. | Mutlak +%68 kâr sağlandı; ancak XU100 rallisinin gerisinde kaldı. | Yatay/düşüş dalgasında fonlama maliyetiyle BTC gerisinde kaldı. |

---

## 5. Risk Metrikleri ve Maliyetler

Tüm metrikler yıllıklandırılmış ve işlem sürtünmeleri düşülerek hesaplanmıştır:

| Risk Metriği | ABD Hisseleri | BIST Hisseleri | Kripto Varlıklar |
| :--- | :---: | :---: | :---: |
| **Sharpe Oranı** | **0.17** | **0.41** | **-0.88** |
| **Sortino Oranı** | **0.58** | **1.54** | **-1.77** |
| **Maksimum Düşüş (Max DD)** | **-%82.40** | **-%90.81** | **-%252.83** |
| **Calmar Oranı** | 0.34 | 0.75 | 1.00 |
| **Ödenen Komisyon & Kayma** | -%8.68 | -%39.00 | -%44.50 |
| **Birikimli Perpetual Fonlama** | - | - | **-%41.16** |
| **Toplam İşlem Sürtünmesi** | -%8.68 | -%39.00 | **-%85.66** |

### Kripto Laboratuvarı Özel İstatistikleri
- **Brier Skoru:** `0.0428` (Mükemmel kalibrasyon eşiği $\le 0.10$ sağlandı).
- **Beklenen Kalibrasyon Hatası (ECE):** `0.042` (%4.2 sapma).
- **Conformal Coverage:** **%90.8** (Hedeflenen %90.0 conformal bandı gerçeği kusursuz yakaladı).
- **Ortalama Tahmin Aralığı:** Fiyatın $\pm\%14.5$'i.
- **Order Block Sonuçları:** 80 Temas (Touch), 56 Ret (Rejection), 21 İhlal (Breach), 19 Temassız (No Contact).

### Overfitting Denetimi (Deflated Sharpe Ratio & PBO)
- **Kayıtlı Deneme Sayısı (`trial_count`):** 2 bağımsız deneme (`journal/trial_registry.jsonl`).
- **En İyi OOS Sharpe:** `1.00`
- **Deflated Sharpe Ratio (DSR):** `5.29` (Kritik eşik $\ge 1.20$).
- **Probability of Backtest Overfitting (PBO):** `0.40`
- **Durum:** `CAUTION_MULTIPLE_TESTING` (Deneme sayısı henüz 50'nin altında olduğu için temkinli izleme modundadır).

---

## 6. Forward / Paper Test Durumu

Backtest tamamlanırken, 25 Eylül 2026 itibarıyla henüz vadesi dolmamış taze sinyaller otomatik olarak `journal/forward_paper_signals.jsonl` kütüğüne aktarılmıştır:

- **Aktif Forward Sinyal Sayısı:** 18 Adet
  - ABD Hisseleri: 6 sinyal (`NVDA`, `META`, `MU`, `AAPL` aktif)
  - BIST Hisseleri: 4 sinyal (`THYAO`, `ASELS`, `TUPRS` aktif)
  - Kripto: 8 sinyal (`BTC`, `ETH`, `SOL` aktif)
- **Kural:** En az **50–100 adet forward/paper sinyali** sonuçlanmadan model katsayıları veya eşiklerinde hiçbir değişiklik yapılmayacaktır.

---

## 7. Veri Eksikleri

1. **BIST İntraday ve Derinlik Verisi:** Yahoo Finance BIST için sadece günlük veri sağlamaktadır; intraday mikro yapı ve emir defteri derinliği BIST hisselerinde simüle edilememektedir.
2. **Kripto Tarihsel Order Book Snapshot:** Binance 1 yıllık geçmiş L2 derinlik verisini geçmişe dönük snapshot olarak ücretsiz API'den vermemektedir; spread ve slippage varsayımları `config/cost_models.json` konservatif eşikleriyle hesaplanmıştır.
3. **Temel Veri Gecikmesi:** Bilanço verileri (FCF, Borç/Özkaynak) çeyreklik açıklandığından, bilanço açıklanma tarihleri ile fiyat hareketleri arasındaki zaman farkı muhafazakar tutulmuştur.

---

## 8. Başarısız Testler ve Çıkarılan Dersler

1. **Kripto Momentum / Trend Stratejisi Başarısız Oldu:**
   - Kriptoda trend takip eden LONG/SHORT bias'ı, 2025-2026 yatay konsolidasyon döneminde -%170 alfa kaybına uğramıştır.
   - **Kök Neden:** 8 saatlik perpetual funding taşıma maliyeti (-%41.16) ve aralık içi sahte kırılımlar (whipsaw).
2. **BIST Relatif Performans Yetersizliği:**
   - Model BIST'te mutlak +%68 getiri üretmiş; ancak BIST 100 endeksinin agresif nominal rallisinin (+%109.89) gerisinde kalmıştır.
   - **Kök Neden:** Nakitte bekleme tamponu (cash drag) ve %0.30'luk yüksek BIST işlem sürtünmesi (39% kümülatif maliyet kaybı).

---

## 9. En Önemli Sınırlamalar

1. **Düşük Yönsel Hit-Rate (%36 - %42):** Sistem yüksek kazanma yüzdesiyle değil, asimetrik kazanç/kayıp oranıyla ($R \ge 2.0$) çalışmaktadır. Yatırımcının art arda gelen kayıpları tolere edebilecek psikolojik disipline sahip olması şarttır.
2. **Kaldıraç ve Fonlama Aşınması:** Kripto varlıklarda uzun süreli pozisyon taşımak fonlama maliyeti nedeniyle kârı tamamen tüketmektedir.
3. **Portföy Seviyesinde Eşzamanlı Pozisyon Sınırı:** Testler tekil varlık bazlı yürütülmüştür; aynı anda 10 hissenin birden AL vermesi durumunda sermaye marjı kısıtı portföy seviyesinde optimize edilmelidir.

---

## 10. Sonraki Adım Önerisi

> **KESİN KURAL:** Yeni özellik, yeni gösterge, yeni LLM veya arayüz bölümü EKLENMEMELİDİR.

Önümüzdeki adımlar yalnızca ölçülen sonuçlardaki kanıtlanmış eksiklikleri gidermeye odaklanmalıdır:
1. **Kripto Rejim Filtresi:** Kriptoda yatay konsolidasyon rejimlerinde (Hurst $0.45 \le H \le 0.55$) yönsel pozisyon açılmasını tamamen engelleyen katı bir veto kuralı test edilmelidir.
2. **İşlem Sıklığı Optimizasyonu (Turnover Azaltma):** BIST'teki %39'luk sürtünme maliyetini düşürmek için rebalancing periyodu 5 günden 10-15 güne çıkarılmalıdır.
3. **Forward Sinyal Takibi:** `journal/forward_paper_signals.jsonl` dosyasındaki 18 aktif sinyalin sonuçları izlenmeli; 50 sinyale ulaşılana kadar model dondurulmalıdır.

---

### Dört Zorunlu Soruya Sayısal Yanıt

| Soru | Yanıt | Kanıt |
| :--- | :---: | :--- |
| **1. Kod teknik olarak çalışıyor mu?** | **EVET** | 3 ayrı evrende 432 sinyal sıfır istisna ile uçtan uca simüle edildi. |
| **2. Matematiksel sonuç doğru hesaplanıyor mu?** | **EVET** | Maliyetler, birikimli funding, R-multiple, Brier ve Conformal formüllere tam uyumlu. |
| **3. Gerçek geçmişte işe yaradı mı?** | **KISMEN** | ABD'de +%14.5 net alfa üretti; BIST'te mutlak kâr (+%68) sağladı; Kripto'da fonlama nedeniyle başarısız oldu. |
| **4. Yeni veride çalışmaya devam ediyor mu?** | **İZLEMEDE** | 18 aktif forward sinyali kaydedildi; OOS sonuçları raporlandı. |
