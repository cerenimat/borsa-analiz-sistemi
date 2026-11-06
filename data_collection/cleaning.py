"""
Ham fiyat verisini temizler (GAB İG-03).

Girdi : data/raw/<SEMBOL>_raw.csv        (fetch_prices.py üretir)
Çıktı : data/processed/<SEMBOL>_clean.csv

Kurallar (keşif bulgularına göre):
  1. Tarih YYYY-MM-DD olmalı; çözülemeyen tarihler silinir.
  2. Fiyat ve hacim sayıya çevrilir; boş veya sayı olmayan satırlar silinir.
  3. Seansı bitmemiş gün (yarım gün) ve gelecek tarihli satırlar silinir.
  4. Fiyatlar 2, düzeltilmiş kapanış 4 ondalık basamağa yuvarlanır.
  5. Aynı (symbol, date) birden fazla kez varsa yalnızca sonuncusu kalır.
  6. Sıfır veya negatif fiyatlı satırlar silinir.
  7. Negatif ya da tam sayı olmayan hacimli satırlar silinir.
  8. low <= open, close <= high kuralına uymayan satırlar silinir.
Borsanın kapalı olduğu günler (hafta sonu, bayram) DOLDURULMAZ.
"""

from datetime import datetime

import pandas as pd

from config import (DAY_COMPLETE_AFTER, PROCESSED_DIR, STOCKS, TIMEZONE,
                    clean_csv_path, raw_csv_path)

COLUMNS = ["symbol", "date", "open", "high", "low",
           "close", "adj_close", "volume"]
PRICE_COLUMNS = ["open", "high", "low", "close"]
NUMERIC_COLUMNS = PRICE_COLUMNS + ["adj_close", "volume"]
PRICE_DECIMALS = 2
ADJ_CLOSE_DECIMALS = 4


def drop_rows(df: pd.DataFrame, mask: pd.Series, rule: str,
              report: dict) -> pd.DataFrame:
    """mask'i True olan satırları siler, silinen sayıyı rapora yazar."""
    report[rule] = int(mask.sum())
    return df.loc[~mask]


def last_complete_date(now: datetime) -> str:
    """Seansı kesin bitmiş son takvim gününü YYYY-MM-DD olarak döndürür.

    Saat DAY_COMPLETE_AFTER'dan önceyse bugün henüz bitmemiş sayılır.
    """
    today = now.date()
    if now.time() < DAY_COMPLETE_AFTER:
        today = today - pd.Timedelta(days=1)
    return today.strftime("%Y-%m-%d")


def clean_prices(df: pd.DataFrame,
                 now: datetime | None = None) -> tuple[pd.DataFrame, dict]:
    """Ham fiyat tablosunu temizler; (temiz_tablo, rapor) döndürür.

    now: "şu an" bilgisi. Verilmezse İstanbul saatiyle şimdiki zaman
    kullanılır; testlerde sabit bir zaman verilebilir.
    """
    missing = [col for col in COLUMNS if col not in df.columns]
    if missing:
        raise ValueError(f"Beklenen sütunlar eksik: {missing}")
    if now is None:
        now = datetime.now(TIMEZONE)

    report = {"girdi_satir": len(df)}
    out = df[COLUMNS].copy()

    # Kural 1: sembol ve tarih standart biçimde
    out["symbol"] = out["symbol"].astype("string").str.strip().str.upper()
    dates = pd.to_datetime(out["date"], format="%Y-%m-%d", errors="coerce")
    out = drop_rows(out, dates.isna(), "gecersiz_tarih", report)
    out["date"] = dates.loc[out.index].dt.strftime("%Y-%m-%d")

    # Kural 2: sayıya çevir; çevrilemeyen değer NaN olur
    for col in NUMERIC_COLUMNS:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    empty = out[NUMERIC_COLUMNS].isna().any(axis=1) | out["symbol"].isna() \
        | (out["symbol"] == "")
    out = drop_rows(out, empty, "eksik_deger", report)

    # Kural 3: seansı bitmemiş gün ve gelecek tarihler
    unfinished = out["date"] > last_complete_date(now)
    out = drop_rows(out, unfinished, "yarim_gun", report)

    # Kural 4: yuvarlama (kontroller yuvarlanmış değerler üzerinde yapılır)
    out[PRICE_COLUMNS] = out[PRICE_COLUMNS].round(PRICE_DECIMALS)
    out["adj_close"] = out["adj_close"].round(ADJ_CLOSE_DECIMALS)

    # Kural 5: aynı hisse + tarih yalnızca bir kez
    duplicate = out.duplicated(subset=["symbol", "date"], keep="last")
    out = drop_rows(out, duplicate, "yinelenen_tarih", report)

    # Kural 6: fiyatlar pozitif olmalı
    non_positive = (out[PRICE_COLUMNS + ["adj_close"]] <= 0).any(axis=1)
    out = drop_rows(out, non_positive, "sifir_negatif_fiyat", report)

    # Kural 7: hacim negatif olamaz ve tam sayı olmalı
    bad_volume = (out["volume"] < 0) | (out["volume"] % 1 != 0)
    out = drop_rows(out, bad_volume, "gecersiz_hacim", report)

    # Kural 8: OHLC tutarlılığı
    inconsistent = (
        (out["high"] < out["low"])
        | (out["open"] > out["high"]) | (out["open"] < out["low"])
        | (out["close"] > out["high"]) | (out["close"] < out["low"])
    )
    out = drop_rows(out, inconsistent, "ohlc_tutarsiz", report)

    out["volume"] = out["volume"].astype("int64")
    out = out.sort_values(["symbol", "date"]).reset_index(drop=True)

    report["cikti_satir"] = len(out)
    report["silinen_toplam"] = report["girdi_satir"] - report["cikti_satir"]
    return out, report


def main() -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    for symbol in STOCKS:
        clean, report = clean_prices(pd.read_csv(raw_csv_path(symbol)))
        clean.to_csv(clean_csv_path(symbol), index=False, encoding="utf-8")
        print(f"=== {symbol} ===")
        for rule, count in report.items():
            print(f"{rule:<22}: {count}")


if __name__ == "__main__":
    main()
