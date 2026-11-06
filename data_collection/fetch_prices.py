"""
config.STOCKS içindeki hisselerin günlük fiyat verisini yfinance'ten çeker,
sütunları ortak biçime çevirir ve ham CSV olarak kaydeder.

Bu aşamada TEMİZLEME YAPILMAZ: değerler yfinance'ten geldiği gibi kalır,
yalnızca sütun adları, sembol ve tarih biçimi standartlaştırılır.
"""

import time

import pandas as pd
import yfinance as yf

from config import START_DATE, STOCKS, RAW_DIR, raw_csv_path, yahoo_symbol

WAIT_SECONDS = 1  # Yahoo'ya art arda hızlı istek atmamak için

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


def fetch_raw(symbol: str, start: str) -> pd.DataFrame:
    """yfinance'ten günlük veriyi hiç değiştirmeden döndürür.

    VeriKaynağıAdaptörü (GAB İOG-A-02): yfinance'e özgü her şey burada.
    """
    df = yf.Ticker(yahoo_symbol(symbol)).history(
        start=start, interval="1d", auto_adjust=False)
    if df.empty:
        raise RuntimeError(f"{symbol} için veri alınamadı.")
    return df


def standardize(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Sütun adlarını, sembolü ve tarih biçimini ortak formata çevirir."""
    missing = [col for col in COLUMN_MAP if col not in df.columns]
    if missing:
        raise ValueError(f"Beklenen sütunlar eksik: {missing}")

    out = df[list(COLUMN_MAP)].rename(columns=COLUMN_MAP)
    out = out.reset_index(drop=True)
    out["date"] = df.index.strftime("%Y-%m-%d").to_list()
    out["symbol"] = symbol  # THYAO (".IS" olmadan)
    return out[OUTPUT_COLUMNS]


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    for symbol in STOCKS:
        print(f"{symbol} verisi çekiliyor ({START_DATE} -> bugün)...")
        prices = standardize(fetch_raw(symbol, START_DATE), symbol)

        output_path = raw_csv_path(symbol)
        prices.to_csv(output_path, index=False, encoding="utf-8")

        print(f"  Kaydedildi: {output_path}")
        print(f"  Satır     : {len(prices)}")
        print(f"  Tarih     : {prices['date'].iloc[0]} -> "
              f"{prices['date'].iloc[-1]}")
        time.sleep(WAIT_SECONDS)


if __name__ == "__main__":
    main()
