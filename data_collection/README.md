# data_collection — Veri Toplama ve Hazırlama Modülü

**Sorumlu:** Elisar Dibek

Bu modül BIST hisselerinin günlük fiyat verisini (OHLCV) yfinance'ten çeker, temizler ve
tüm ekibin kullandığı ortak SQLite veritabanına (`data/borsa.db`) kaydeder. Veritabanı
şeması haber, KAP, yorum ve duygu analizi tablolarını da içerir.

İlgili gereksinimler: İG-02, İG-03, İG-04, İG-05, İG-25, İOG-G-01, İOG-G-04, İOG-A-02, İOG-D-03.

## Dosyalar

| Dosya | Görevi |
|---|---|
| `schema.sql` | Ortak veritabanı şeması: tüm tablolar ve görünümler |
| `config.py` | Ortak ayarlar: hisse listesi, başlangıç tarihi, seans saati, dosya yolları |
| `fetch_prices.py` | yfinance'ten ham fiyat verisini çeker → `data/raw/<SEMBOL>_raw.csv` |
| `cleaning.py` | Temizleme kuralları (`clean_prices()`) |
| `database.py` | Şemayı kurar, hisseleri ve temiz fiyatları yükler, işlem günlerini atar |
| `check_db.py` | Veritabanını salt okunur olarak doğrular |
| `verify_prices.py` | Fiyat teyidi: sonradan halka arz, eksik/fazla günler → `data/processed/price_verification.csv` |
| `explore_yfinance.py` | İlk keşif betiği (yalnızca ekrana yazar, hiçbir şey kaydetmez) |

Hisse listesinin tek kaynağı proje kökündeki `config/bist50_oid.json` dosyasıdır
(BIST 50: sembol, şirket adı, KAP kimliği). Ceren'in KAP betiği de aynı dosyayı okur.

## Kurulum

Python **3.12** gerekir. Proje kökünde (Windows PowerShell):

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Çalıştırma sırası

```powershell
python data_collection\fetch_prices.py   # 1. Ham fiyatları çeker (50 hisse, birkaç dakika)
python data_collection\database.py       # 2. Temizler ve data/borsa.db'ye yazar
python data_collection\check_db.py       # 3. Doğrulama (isteğe bağlı)
python tests\test_trading_dates.py       # Test (isteğe bağlı)
```

`database.py` tekrar çalıştırılabilir: aynı kayıt iki kez eklenmez, var olan kayıt
güncellenir.

**Fiyatsız veritabanı (Ceren için):** `data/raw` klasörü boşken `database.py`
çalıştırılırsa şema ve 50 hisselik `stocks` tablosu kurulur, fiyatlar atlanır. KAP verisi
bu veritabanına yüklenebilir. Birleştirmeden sonra `database.py` yeniden çalıştırılınca
boş `trading_date` alanları doldurulur.

## Veritabanı

Şemanın tamamı `schema.sql` dosyasındadır. Her bağlantıda `PRAGMA foreign_keys = ON`
çalıştırılmalıdır.

| Tablo / görünüm | İçerik | Kimin? |
|---|---|---|
| `stocks` | Hisseler: `symbol`, `name`, `yahoo_symbol`, `kap_oid` | Elisar |
| `prices` | Günlük OHLCV; `(symbol, date)` benzersiz | Elisar |
| `trading_days` (görünüm) | Fiyatı olan günler (işlem günü takvimi) | Elisar |
| `contents` | Haber, KAP bildirimi ve yorumlar; `(source, source_id)` benzersiz | Ceren |
| `content_symbols` | İçerik–hisse bağlantısı (çoka-çok) | Ceren |
| `sentiments` | Duygu sonuçları; `(content_id, model)` benzersiz | Ceren |
| `daily_sentiment` (görünüm) | Günlük haber ve yorum ortalamaları (Sümeyye'nin modeline girdi) | — |
| `update_log` | Her yüklemenin özeti (`yfinance` / `kap` / `news` / `youtube` / `forum`) | Herkes |

Veritabanına elle kayıt eklenmez veya silinmez; veri yalnızca betiklerle değişir.

## Veri biçimi

- **Sembol:** `THYAO` (`.IS` eki yalnızca `stocks.yahoo_symbol` alanında).
- **Tarih:** `YYYY-MM-DD`. Yalnızca işlem günleri vardır; hafta sonu ve bayramlar doldurulmaz.
- **Zaman:** `YYYY-MM-DDTHH:MM:SS+03:00` (İstanbul saati).
- **Fiyatlar:** TL; `open`, `high`, `low`, `close` 2 basamak, `adj_close` 4 basamak.
- **`close`:** O gün işlem gören fiyat (grafik için uygun).
  **`adj_close`:** Temettüye göre düzeltilmiş fiyat (model için uygun); yeni temettüde
  geçmiş değerler güncellenebilir.
- **İşlem günü ataması (İG-10):** 18:10 ve sonrasında yayımlanan içerik bir sonraki işlem
  gününe atanır. Fiyat tablosunda henüz sonraki işlem günü yoksa `trading_date` boş kalır.

## Temizleme kuralları (İG-03)

1. Tarih `YYYY-MM-DD` olmalı; çözülemeyen tarihler silinir.
2. Boş veya sayı olmayan fiyat/hacim içeren satırlar silinir.
3. Seansı bitmemiş gün silinir: 18:30'dan önce bugünün satırı kaydedilmez.
4. Fiyatlar 2, `adj_close` 4 basamağa yuvarlanır.
5. Aynı `(symbol, date)` yalnızca bir kez (sonuncusu) tutulur.
6. Sıfır veya negatif fiyatlı satırlar silinir.
7. Negatif ya da tam sayı olmayan hacimli satırlar silinir.
8. `low ≤ open, close ≤ high` kuralına uymayan satırlar silinir.

Her kuralın kaç satırı sildiği `update_log.detail` alanına JSON olarak yazılır.

## Bilinen sınırlılıklar

- **yfinance resmî bir API değildir;** hizmet sürekliliği garanti edilmez ve yoğun isteklerde
  erişim geçici olarak engellenebilir. Veri bir kez çekilip veritabanında saklanır.
- **Sonradan halka arz olan hisseler** 01.01.2023'ten sonra başlar: ASTOR (2023-01-18),
  CVKMD (2023-04-13), CWENE (2023-05-10), ENERY (2023-08-23), GLRMK (2025-01-17).
  GLRMK'nin verisi 3 yılın altındadır (yaklaşık 1,8 yıl).
- **2024-04-09 (Ramazan Bayramı arifesi):** Borsa 13:00'a kadar açıktı, ancak Yahoo bu günün
  verisini 50 hisseden yalnızca 15'i için veriyor. Diğer 35 hissede bu gün eksik; uydurma
  veriyle doldurulmadı.
- **Bayram arifeleri:** Borsa yarım gün çalışır; ilk sürümde 18:10 kuralı bu günlerde de uygulanır.
- **TRMET ve TRALT** Kasım 2025'te KOZAA ve KOZAL kodlarından yeni kodlarına geçti; Yahoo eski
  geçmişi yeni kodlara taşımış, 2023'ten itibaren veri kesintisiz.

## Veri ve lisans

- Veri dosyaları (`data/`) repoya eklenmez (İOG-Y-02); herkes veritabanını betiklerle
  kendi bilgisayarında üretir veya ekip içinde Drive'dan alır.
- Veri yalnızca akademik amaçla kullanılır.
- Kullanılan kütüphaneler ve lisansları (İOG-Y-05): yfinance (Apache 2.0),
  pandas (BSD 3-Clause), NumPy (BSD 3-Clause).