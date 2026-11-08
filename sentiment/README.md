# Haber ve Duygu Analizi (sentiment/)

Sorumlu: Ceren

## Betikler

| Betik | Ne yapar | Yazdığı tablolar |
|---|---|---|
| `fetch_kap.py` | BIST 50 için 01.01.2023'ten bugüne KAP bildirimlerini çeyrek çeyrek çeker | `contents`, `content_symbols`, `update_log` |
| `fetch_youtube.py` | Her hisse için 2023'ten bugüne Türkçe videoları yıl yıl arar (başlığında hisse kodu geçenler), yorumlarını çeker | `contents`, `content_symbols`, `update_log` |
| `fetch_news.py` | Her hisse için 2023'ten bugüne Google Haberler RSS aramasını ay ay yapar; başlığında şirket adı/kodu geçen haberleri tutar | `contents`, `content_symbols`, `update_log` |
| `merge_sources.py` | `google_news.db` ve `youtube.db` içeriğini ortak veritabanına aktarır | hedefte `contents`, `content_symbols`, `update_log` |

## Çalıştırma (proje kökünden, `.venv` etkinken)

```bash
python sentiment/fetch_kap.py                # 50 hissenin tamamı (yaklaşık 15–20 dk)
python sentiment/fetch_kap.py THYAO PGSUS    # yalnızca bu hisseler
```

Veritabanı yoksa şema ve `stocks` tablosu kurulur (`data_collection/database.py`). Fiyat verisi olmayan
veritabanında `trading_date` boş kalır; fiyatlar yüklendikten sonra `assign_trading_dates()` doldurur.

## Notlar

- KAP herkese açık API sunmaz; betik KAP sitesinin kendi sorgu uç noktasını kullanır, istekler arasında bekler
  ve yalnızca başlık, kısa özet, tarih, kaynak ve bağlantıyı saklar (İOG-Y-03).
- Bir bildirim `contents` tablosuna bir kez yazılır; geldiği her hisse için `content_symbols` satırı eklenir
  (ortak bildirimler, BIST toplu duyuruları).
- `source` = bildirimi yapan kurum (KAP'taki `kapTitle`). BIST, MKK ve Takasbank duyurularında
  `is_company_notice = 0` olur ve günlük duygu skoruna girmez.
- Betiği tekrar çalıştırmak güvenlidir: var olan bildirim tekrar eklenmez, eksik hisse bağlantıları tamamlanır.
  Alınamayan sorgular `update_log` tablosunda `status = 'error'` olarak görünür; tekrar çalıştırınca doldurulur.

## YouTube (`fetch_youtube.py`)

```bash
cp .env.example .env                                   # .env içine YOUTUBE_API_KEY=... yaz
python sentiment/fetch_youtube.py                      # 50 hissenin tamamı
python sentiment/fetch_youtube.py THYAO PGSUS          # yalnızca bu hisseler
python sentiment/fetch_youtube.py --retry-failed       # başarılı çalışması olmayan hisseler
python sentiment/fetch_youtube.py --db data/test.db    # başka bir veritabanı dosyası
```

- Arama: `"<KOD> hisse"`, Türkçe; 2023, 2024, 2025 ve 2026 **ayrı ayrı** aranır (alaka sıralaması yeni
  videoları öne çıkardığı için eski yıllar yoksa kaybolur). Her yıldan başlığında hisse kodu geçen en fazla
  20 video, video başına en yeni 200 üst düzey yorum (yanıtlar alınmaz). Seçilen videolar ve yıllara göre
  sayıları `update_log.detail` alanında saklanır (yöntemin raporlanması için).
- Kullanıcı adı, kanal ve profil bilgisi saklanmaz (İOG-Y-04); `title` = video başlığı, `text` = yorum.
- Saatler UTC'den `+03:00`'a çevrilir; 18:10 kuralı KAP'taki gibi işler.
- Günlük API kotası 10.000 birim: arama 100, 100 yorumluk sayfa 1 birim; hisse başına yaklaşık 450–500
  birim, 50 hisse yaklaşık 3 gün. Kota biterse (YouTube 429 ya da 403 `quotaExceeded` döner) betik 1–2 dk
  bekleyip tekrar dener, olmazsa durur; ertesi gün `--retry-failed` ile kalan hisselerden, yarım kalan
  hissede de bitmemiş yıllardan devam edilir (biten yıllar tekrar aranmaz).
- API anahtarı hiçbir kayda yazılmaz; hata mesajlarından istek adresi ve anahtar temizlenir.

## Haberler (`fetch_news.py`)

```bash
python sentiment/fetch_news.py --db data/google_news.db                 # 50 hissenin tamamı (~1 saat)
python sentiment/fetch_news.py --db data/google_news.db --retry-failed  # yarım kalan hisseler / aylar
```

- Sorgu: `("<şirket adı>" OR <takma ad> OR <KOD>) hisse after:<ay> before:<sonraki ay>`; eski kodlar da
  aranır (TRALT = Koza Altın/KOZAL, TRMET = Koza Anadolu/KOZAA, 2025 Kasım öncesi).
- Başlığında şirket adı, takma adı ya da kodu geçmeyen haberler kaydedilmez (konu dışı).
- Yalnızca başlık, kaynak, tarih ve bağlantı saklanır (İOG-Y-03); `text` = başlık.
- **Kısıtlar:** Google eski aylar için daha az haber döndürür (2023'te az, 2026'da çok). Eski haberlerde
  yayın saati çoğunlukla gerçek değildir (10:00/11:00 görünür); bu yüzden haberlerde 18:10 kuralı gün
  düzeyinde kalır. t gününün duygusu t+1'i tahmin etmek için kullanıldığında sızıntı oluşmaz.

## Kaynakları birleştirme (`merge_sources.py`)

YouTube kotası ve değişen arama sonuçları yüzünden bu toplayıcılar ortak veritabanında yeniden
çalıştırılmaz; ayrı dosyalara toplanan veri bu betikle aktarılır.

```bash
python sentiment/merge_sources.py --target data/borsa.db --dry-run   # yalnızca rapor, yazmaz
python sentiment/merge_sources.py --target data/borsa.db             # aktar
```

- Kaynak dosyalar salt okunur açılır. Aynı içerik (`source` + `source_id`) ikinci kez eklenmez; tekrar
  çalıştırmak güvenlidir. Kimlikler hedefin kimliklerine çevrilir, `update_log` kayıtları da taşınır.
- Sonunda `assign_trading_dates()` çalışır; ~23 bin satırda birkaç dakika sürebilir.
