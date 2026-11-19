# Tahmin Modülü (`forecasting/`)

BIST 50 hisseleri için geçmiş fiyat (`prices`) ve günlük duygu analizi (`daily_sentiment`) verilerini kullanarak bir sonraki işlem gününün yönünü (`Yükseliş` / `Düşüş`) tahmin eden makine öğrenmesi modülüdür.

## Dosya Yapısı

- `features.py`: `data/borsa.db` veritabanından `adj_close` ve `BERTurk` duygu skorlarını `LEFT JOIN` ile birleştirir; teknik göstergeleri (günlük getiri, 20/50 günlük hareketli ortalama, 20 günlük volatilite, 14 günlük RSI) ve 5 günlük duygu ortalamalarını hesaplar. Veri sızıntısını önlemek için `t` gününün özellikleriyle `t+1` gününün yönünü hedefler.
- `models.py`: Ortak soyut `TahminModeli` arayüzü ile `CogunlukSinifiModeli` (baseline), `LojistikRegresyonModeli` ve `RastgeleOrmanModeli` sınıflarını içerir (`random_state=42`).
- `train.py`: Zaman sıralı (%80 eğitim / %20 test) ayrımla modelleri eğitir, değerlendirir ve `models/<SEMBOL>/` altına `.joblib` + `metrics.json` olarak kaydeder.
- `predict.py`: Kayıtlı modelleri yükleyerek bir sonraki işlem günü için yön ve olasılık tahmini döndürür (FastAPI entegrasyonu için).
- `compare_sentiment.py`: Duygu özelliklerinin etkisini ölçmek için duygusuz (yalnızca fiyat) ve duygulu (fiyat + duygu) modelleri karşılaştırır (İG-23).

## Kullanım

Tüm komutlar proje kök dizininden ve `.venv` aktifken çalıştırılır:

```powershell
# Tek hisse eğitimi
python -m forecasting.train --symbol THYAO

# Tüm BIST 50 hisseleri için toplu eğitim
python -m forecasting.train --all

# Bir sonraki işlem günü tahmini (JSON çıktı)
python -m forecasting.predict --symbol THYAO

# Duygulu vs. duygusuz özellik karşılaştırması
python -m forecasting.compare_sentiment --all

# Veri sızıntısı ve tekrarlanabilirlik birim testleri
python -m unittest tests/test_forecasting.py -v
