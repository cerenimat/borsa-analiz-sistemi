"""
Bir BIST hissesinin günlük fiyat verisini yfinance'ten çeker,
sütunları ortak biçime çevirir ve ham CSV olarak kaydeder.

Bu aşamada TEMİZLEME YAPILMAZ: değerler yfinance'ten geldiği gibi kalır,
yalnızca sütun adları ve tarih biçimi standartlaştırılır.
"""

from pathlib import Path

import pandas as pd
import yfinance as yf

SYMBOL = "THYAO.IS"
PERIOD = "5y"

# Bu dosya data_collection/ içinde; iki üst klasör proje kök dizini.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw"

# yfinance sütun adı -> bizim standart sütun adımız
COLUMN_MAP = {
    "Open": "open",
    "High": "high",
    "Low": "low",
    "Close": "close",
    "Adj Close": "adj_close",
    "Volume": "volume",
}

OUTPUT_COLUMNS = ["symbol", "date", "open", "high", "low",
                  "close", "adj_close", "volume"]


def fetch_raw(symbol: str, period: str) -> pd.DataFrame:
    """yfinance'ten günlük veriyi hiç değiştirmeden döndürür."""
    df = yf.Ticker(symbol).history(period=period, interval="1d",
                                   auto_adjust=False)
    if df.empty:
        raise RuntimeError(f"{symbol} için veri alınamadı.")
    return df


def standardize(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Sütun adlarını ve tarih biçimini ortak formata çevirir."""
    missing = [col for col in COLUMN_MAP if col not in df.columns]
    if missing:
        raise ValueError(f"Beklenen sütunlar eksik: {missing}")

    out = df[list(COLUMN_MAP)].rename(columns=COLUMN_MAP)
    out = out.reset_index(drop=True)
    out["date"] = df.index.strftime("%Y-%m-%d").to_list()
    out["symbol"] = symbol
    return out[OUTPUT_COLUMNS]


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    print(f"{SYMBOL} verisi çekiliyor...")
    raw = fetch_raw(SYMBOL, PERIOD)
    prices = standardize(raw, SYMBOL)

    file_name = SYMBOL.replace(".", "_") + "_raw.csv"
    output_path = RAW_DIR / file_name
    prices.to_csv(output_path, index=False, encoding="utf-8")

    print(f"Kaydedildi : {output_path}")
    print(f"Satır      : {len(prices)}")
    print(f"Tarih      : {prices['date'].iloc[0]} -> {prices['date'].iloc[-1]}")
    print("\nİlk 3 satır:")
    print(prices.head(3).to_string(index=False))
    print("\nVeri türleri:")
    print(prices.dtypes)


if __name__ == "__main__":
    main()