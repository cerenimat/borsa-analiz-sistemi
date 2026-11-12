# Haber ve Duygu Analizi (sentiment/)

Sorumlu: Ceren

## Betikler

| Betik | Ne yapar | Yazdığı tablolar |
|---|---|---|
| `fetch_kap.py` | BIST 50 için 01.01.2023'ten bugüne KAP bildirimlerini çeyrek çeyrek çeker | `contents`, `content_symbols`, `update_log` |
| `fetch_youtube.py` | Her hisse için 2023'ten bugüne Türkçe videoları yıl yıl arar (başlığında hisse kodu geçenler), yorumlarını çeker | `contents`, `content_symbols`, `update_log` |
| `fetch_news.py` | Her hisse için 2023'ten bugüne Google Haberler RSS aramasını ay ay yapar; başlığında şirket adı/kodu geçen haberleri tutar | `contents`, `content_symbols`, `update_log` |
| `fetch_forum.py` | Hisse.net'te her hissenin forum konusundan 2023'ten bugüne gönderileri çeker | `contents`, `content_symbols`, `update_log` |
| `text_filter.py` | Hangi içeriklerin puanlanacağını seçer ve model girdisini temizler (İG-11); diğer betikler kullanır | — |
| `make_validation_set.py` | Elle etiketlenecek doğrulama kümelerini (2 × 200 satır) Excel'e çıkarır | `data/validation/*.xlsx` |
| `make_training_set.py` | Doğrulama satırlarıyla çakışmayan 2.000 satırlık eğitim kümesini çıkarır | `data/training/train_set.csv` |
| `train_model.py` | BERTurk'ü eğitim kümesiyle ince ayarlar | `data/models/berturk-sentiment/` |
| `evaluate_models.py` | Hazır modelleri ve ince ayarlı modeli doğrulama kümelerinde karşılaştırır | `data/validation/eval_results.md` |
| `score_contents.py` | Puanlanacak içerikleri ince ayarlı modelle puanlar | `sentiments` |
| `export_sentiments.py` | Duygu puanlarını ve puanlanan içerikleri ortak veritabanına aktarılacak ayrı bir dosyaya çıkarır | çıktı dosyasında `sentiments`, `contents`, `content_symbols`, `stocks` |
| `update_sentiment.py` | Dört kaynağı güncelleme kipinde toplar, yeni metinleri puanlar, yalnızca yenileri ayrı bir dosyaya çıkarır | `data/work.db`; çıktı `data/updates/update_<tarih>.db` |
| `incremental.py` | Güncellemede her hissenin başlangıç tarihini hesaplar; toplayıcılar kullanır | — |
| `merge_sources.py` | `google_news.db`, `youtube.db`, `hissenet.db` ve puan dosyasının içeriğini ortak veritabanına aktarır | hedefte `contents`, `content_symbols`, `update_log`, `sentiments` |

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

## Forum (`fetch_forum.py`)

```bash
python sentiment/fetch_forum.py --db data/hissenet.db                 # 50 hissenin tamamı
python sentiment/fetch_forum.py --db data/hissenet.db THYAO PGSUS     # yalnızca bu hisseler
python sentiment/fetch_forum.py --db data/hissenet.db --retry-failed  # yarım kalan hisseler
python sentiment/fetch_forum.py --db data/forum_test.db --check       # yalnızca bulunan konuları listeler
```

- Hisse.net (vBulletin) pazar alt forumlarında her hissenin bir konusu var; betik konuyu bulur, 2023 öncesi
  sayfaları ikili aramayla atlar ve 01.01.2023'ten bugüne tüm gönderileri yazar (`type = 'comment'`,
  `source = 'Hisse.net'`, `update_log.source = 'forum'`).
- Yalnızca gönderi metni (alıntılanan eski gönderiler çıkarılır), tarih, konu başlığı ve bağlantı saklanır.
  Kullanıcı adı, unvan, imza ve profil bilgisi saklanmaz (İOG-Y-04). robots.txt'nin yasakladığı sayfalara
  istek atılmaz; istekler arasında beklenir.
- Tekrar çalıştırmak güvenlidir: her konu son okunan sayfadan devam eder, var olan gönderi tekrar eklenmez.
- `'forum'` kaynağı şemadaki `update_log` izin listesinde yoksa betik (ve `merge_sources.py`) ekler.

## Duygu modeli

Model betiklerinin paketleri (PyTorch, Transformers…) ortak `requirements.txt`'de değil; ortak paketlerle
birlikte şöyle kurulur:

```bash
pip install -r sentiment/requirements-model.txt
```

```bash
python sentiment/make_validation_set.py --db data/work.db              # 1. küme (doğal dağılım)
python sentiment/make_validation_set.py --db data/work.db --batch 2    # 2. küme (ayıklanmış metinler)
python sentiment/make_training_set.py --db data/work.db
python sentiment/train_model.py                                        # ~440 MB model, Git'e girmez
python sentiment/evaluate_models.py --db data/work.db --files data/validation/validation_set.xlsx data/validation/validation_set_2.xlsx
python sentiment/score_contents.py --db data/work.db --dry-run         # yalnızca sayar
python sentiment/score_contents.py --db data/work.db
```

- Doğrulama kümeleri elle etiketlenir ve modelin ölçüldüğü tek kaynaktır; eğitime hiç girmez
  (`make_training_set.py` bu satırları kaynak + kimlik ve metin üzerinden dışarıda bırakır).
- Eğitim kümesinin etiketleri (`labeler` sütunu) bir dil modeliyle üretildi; modelin başarısı yalnızca elle
  etiketlenmiş doğrulama kümelerinde ölçülür.
- `score_contents.py` yalnızca puanı olmayan içerikleri puanlar; tekrar çalıştırmak güvenlidir. Model yeniden
  eğitilirse `--rescore` eski puanları silip baştan puanlar.
- Model ve veri dosyaları `data/` altında durur, Git'e girmez (İOG-Y-02); puanlar diğer makinelere
  `export_sentiments.py` ile gider.

**Model karşılaştırması** (`evaluate_models.py`, 2026-11-09). İki doğrulama kümesi birlikte değerlendirildi:
her grupta 200 elle etiketlenmiş metin (haber = haber başlığı + KAP; yorum = YouTube + forum).

| Model | Haber doğruluk | Haber makro-F1 | Yorum doğruluk | Yorum makro-F1 |
|---|---|---|---|---|
| Hep nötr (taban çizgisi) | 0,555 | 0,238 | 0,635 | 0,259 |
| FinTurkBERT (hazır) | 0,600 | 0,406 | 0,640 | 0,281 |
| BounTi (hazır) | 0,575 | 0,337 | 0,455 | 0,420 |
| **BERTurk-FT (ince ayarlı, kullanılan)** | **0,755** | **0,684** | **0,750** | **0,649** |

Yalnızca puanlanan metinlerde (`text_filter.py` sonrası; haber 187, yorum 165) BERTurk-FT: haber 0,738 / 0,676,
yorum 0,697 / 0,631. %95 güven aralıkları ve sınıf bazında sonuçlar `data/validation/eval_results.md`'de.

## Duygu puanları (`export_sentiments.py`)

Puanlama ince ayarlı BERTurk modeliyle (~440 MB, Git'te yok) tek makinede yapılır; puanlar ortak veritabanına
bu dosya üzerinden gelir:

```bash
python sentiment/export_sentiments.py --db data/work.db                       # -> data/sentiments_berturk.db
python sentiment/merge_sources.py data/sentiments_berturk.db --target data/borsa.db
```

- Kaynak veritabanı salt okunur açılır; var olan çıktı dosyasının üzerine yazılmaz. Şema sürümleri uyuşmazsa
  betik durur.
- `merge_sources.py` içerikleri hedefte `source` + `source_id` ile eşler; aynı içerik + model için gelen yeni
  puan eskisinin yerine yazılır.

**Puanlanmayan içerikler.** Hisse hakkında görüş taşımayan metinler günlük ortalamayı nötre çeker; bu yüzden
puanlanmazlar (`contents`'te kalırlar, yalnızca `sentiments` satırları yoktur):

- KAP: yalnızca şirketin kendi özel durum açıklamaları (`category = 'ODA'`) puanlanır. Rutin bildirimler
  (DG: genel kurul, bono itfası…; FR: finansal rapor; DKB) ve BIST/MKK/Takasbank duyuruları
  (`is_company_notice = 0`) yön taşımadığı için dışarıda kalır.
- Haberler: hepsi puanlanır (konu dışı başlıklar zaten `fetch_news.py`'de elenir).
- Yorum ve forum gönderileri: reklam içerenler (spam), harf/rakam sayısı 4'ten az olanlar, görüş ifadesi
  (fiyat, hedef, al/sat, kâr/zarar, sayı…) içermeyen 200 karakterden kısa teşekkür/övgü ("emeğinize sağlık
  hocam") ve video isteği yorumları dışarıda kalır. YouTube'da bağlantı içeren yorum reklam sayılır (bot,
  kurs, üyelik linkleri); forumda bağlantılar paylaşılan haberdir, kontrolden önce silinir. Forum mobil
  uygulama imzaları ("… hisse.net mobile app kullanarak gönderildi", Tapatalk) hem kontrolden hem model
  girdisinden çıkarılır.

Kurallar ilk 200 satırlık etiketli doğrulama kümesine bakılarak belirlendi, ikinci bağımsız kümeyle kontrol
edildi.

## Güncelleme (`update_sentiment.py`)

Yeni içerikler tek komutla toplanır, puanlanır ve ortak veritabanına gidecek küçük bir dosyaya çıkarılır:

```bash
python sentiment/update_sentiment.py                     # dört kaynak, data/work.db (~20 dk)
python sentiment/update_sentiment.py --skip youtube      # YouTube olmadan (kota bittiyse)
python sentiment/merge_sources.py data/updates/update_<tarih>.db --target data/borsa.db   # ortak veritabanı
```

- KAP, haber ve YouTube toplayıcıları `--update` ile çalışır: her hisse kendi son başarılı çalıştırmasından
  7 gün önce başlar (geç yayımlanan içerik kaçmasın diye; var olanlar tekrar eklenmez). Forum zaten her
  konuyu son okunan sayfadan sürdürür.
- YouTube'da güncelleme geçmişle **aynı yöntemi** kullanır: içinde bulunulan yıl, alaka sırasıyla en fazla
  20 video; bu videoların yorumları yeniden okunur (sonradan gelen yorumlar da girer). Yalnızca en yeni
  videoları almak son günlerin yorum sayısını yapay olarak artırırdı. Maliyet hisse başına ~120 birim,
  50 hisse günlük kotaya sığar.
- Bir kaynak hata verirse (ağ, kota, Google engeli) diğerleri sürer; o kaynak bir sonraki güncellemede
  kendi son başarılı çalıştırmasından devam eder.
- Çıktı dosyası bu çalıştırmada eklenen içerikleri, bağlantılarını, puanlarını ve `update_log` satırlarını
  içerir; aynı dosyayı iki kez birleştirmek bir şeyi çoğaltmaz.
- **Haber sayısı:** Google yeni haberleri çok, eskileri az döndürür; güncellemeyle son günlerde haber sayısı
  belirgin artar (ör. Eylül 2026'da günde ~18, Kasım'ın ilk haftasından sonra günde 100+). Ortalama skor
  bundan etkilenmez, ama `news_count` ham haliyle dönemler arasında karşılaştırılamaz.

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
