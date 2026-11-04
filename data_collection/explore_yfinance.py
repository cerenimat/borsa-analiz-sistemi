"""
Keşif betiği: yfinance'ten THYAO.IS günlük verisini çekip yapısını inceler.

Bu betik hiçbir dosyaya veri KAYDETMEZ; yalnızca ekrana bilgi yazar.
Amaç, temizleme kodunu yazmadan önce verinin neye benzediğini görmektir.
"""

import pandas as pd
import yfinance as yf

SYMBOL = "THYAO.IS"  # Borsa İstanbul hisseleri Yahoo'da ".IS" ekiyle geçer
PERIOD = "5y"        # Son 5 yıl (hedefimiz en az 3 yıl)


def main() -> None:
    # Tablolar terminalde alt satıra kaymadan görünsün
    pd.set_option("display.width", 140)
    pd.set_option("display.max_columns", 20)

    print(f"{SYMBOL} için son {PERIOD} günlük veri isteniyor...")

    ticker = yf.Ticker(SYMBOL)
    # auto_adjust=False: hem ham kapanışı (Close) hem düzeltilmiş
    # kapanışı (Adj Close) görmek için düzeltmeyi kapatıyoruz.
    df = ticker.history(period=PERIOD, interval="1d", auto_adjust=False)

    if df.empty:
        print("Veri gelmedi. İnternet bağlantısını veya sembolü kontrol et.")
        return

    print("\n=== BOYUT ===")
    print(f"Satır sayısı: {len(df)} | Sütun sayısı: {df.shape[1]}")

    print("\n=== SÜTUNLAR VE VERİ TÜRLERİ ===")
    print(df.dtypes)

    print("\n=== TARİH (INDEX) BİLGİSİ ===")
    print("Index türü :", type(df.index).__name__)
    print("Index adı  :", df.index.name)
    print("Saat dilimi:", df.index.tz)
    print("İlk tarih  :", df.index.min())
    print("Son tarih  :", df.index.max())

    print("\n=== İLK 3 SATIR ===")
    print(df.head(3))

    print("\n=== SON 3 SATIR ===")
    print(df.tail(3))

    print("\n=== HIZLI KALİTE KONTROLÜ ===")
    print("Sütun başına boş değer sayısı:")
    print(df.isna().sum())
    print("Yinelenen tarih sayısı :", df.index.duplicated().sum())
    print("Negatif hacimli gün    :", (df["Volume"] < 0).sum())
    print("Sıfır hacimli gün      :", (df["Volume"] == 0).sum())
    print("High < Low olan gün    :", (df["High"] < df["Low"]).sum())
    if "Adj Close" in df.columns:
        farkli = (df["Close"] != df["Adj Close"]).sum()
        print("Close != Adj Close gün :", farkli)

    # ---------------- YENİ: Adım 8 ----------------

    print("\n=== TEMETTÜ VE BÖLÜNME GÜNLERİ ===")
    olay_var = (df["Dividends"] != 0) | (df["Stock Splits"] != 0)
    olaylar = df.loc[olay_var, ["Close", "Adj Close", "Dividends", "Stock Splits"]]
    if olaylar.empty:
        print("Bu dönemde temettü veya bölünme yok.")
    else:
        print(olaylar)

    print("\n=== FİYAT TUTARLILIĞI ===")
    fiyatlar = df[["Open", "High", "Low", "Close"]]
    sifir_negatif = (fiyatlar <= 0).any(axis=1).sum()
    acilis_disarida = ((df["Open"] > df["High"]) | (df["Open"] < df["Low"])).sum()
    kapanis_disarida = ((df["Close"] > df["High"]) | (df["Close"] < df["Low"])).sum()
    print("Sıfır/negatif fiyatlı gün        :", sifir_negatif)
    print("Açılış, Low-High aralığı dışında :", acilis_disarida)
    print("Kapanış, Low-High aralığı dışında:", kapanis_disarida)

    print("\n=== TARİH BOŞLUKLARI ===")
    # Her işlem günü ile bir önceki işlem günü arasındaki takvim günü farkı
    bosluk = df.index.to_series().diff().dt.days
    print("Ardışık iki işlem günü arasındaki gün farkı -> kaç kez görüldü:")
    print(bosluk.value_counts().sort_index())
    print("\n4 günden uzun boşluklar (tatil mi, eksik veri mi?):")
    uzun = bosluk[bosluk > 4]
    if uzun.empty:
        print("Yok.")
    else:
        print(uzun)


if __name__ == "__main__":
    main()