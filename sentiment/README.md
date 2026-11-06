# Haber ve Duygu Analizi (sentiment/)

Sorumlu: Ceren

## Betikler

| Betik | Ne yapar | Yazdığı tablolar |
|---|---|---|
| `fetch_kap.py` | BIST 50 için 01.01.2023'ten bugüne KAP bildirimlerini çeyrek çeyrek çeker | `contents`, `content_symbols`, `update_log` |

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
