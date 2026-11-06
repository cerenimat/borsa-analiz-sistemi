"""
config.STOCKS içindeki hisselerin günlük fiyat verisini yfinance'ten çeker,
sütunları ortak biçime çevirir ve ham CSV olarak kaydeder.

Bu aşamada TEMİZLEME YAPILMAZ: değerler yfinance'ten geldiği gibi kalır,
yalnızca sütun adları, sembol ve tarih biçimi standartlaştırılır.

Kullanım:
  python data_collection\\fetch_prices.py              # tüm hisseler
  python data_collection\\fetch_prices.py THYAO ASELS  # yalnızca bunlar
"""

import sys
import time

import pandas as pd
import yfinance as yf

from config import START_DATE, STOCKS, RAW_DIR, raw_csv_path, yahoo_symbol

WAIT_SECONDS = 1   # Yahoo'ya art arda hızlı istek atmamak için
MAX_ATTEMPTS = 3   # GAB UC-06: servis yanıt vermezse en fazla 3 deneme

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
    Hata ya da boş yanıt gelirse MAX_ATTEMPTS kez dener; giderek daha
    uzun bekler (2, 4 saniye).
    """
    last_error = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            df = yf.Ticker(yahoo_symbol(symbol)).history(
                start=start, interval="1d", auto_adjust=False)
            if not df.empty:
                return df
            last_error = RuntimeError("boş yanıt (veri yok)")
        except Exception as err:  # ağ hatası, Yahoo engeli vb.
            last_error = err
        if attempt < MAX_ATTEMPTS:
            time.sleep(2 ** attempt)
    raise RuntimeError(f"{MAX_ATTEMPTS} denemede alınamadı: {last_error}")


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


def fetch_symbol(symbol: str) -> pd.DataFrame:
    """Bir hissenin verisini çeker, standartlaştırır ve ham CSV'ye yazar."""
    prices = standardize(fetch_raw(symbol, START_DATE), symbol)
    prices.to_csv(raw_csv_path(symbol), index=False, encoding="utf-8")
    return prices


def selected_symbols(args: list[str]) -> list[str]:
    """Komut satırında sembol verildiyse onları, yoksa tüm listeyi döndürür."""
    if not args:
        return list(STOCKS)
    symbols = [arg.upper() for arg in args]
    unknown = [s for s in symbols if s not in STOCKS]
    if unknown:
        raise SystemExit(f"Listede olmayan sembol: {', '.join(unknown)}")
    return symbols


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    symbols = selected_symbols(sys.argv[1:])
    print(f"{len(symbols)} hisse çekilecek ({START_DATE} -> bugün)\n")

    failed = {}
    for i, symbol in enumerate(symbols, start=1):
        try:
            prices = fetch_symbol(symbol)
        except Exception as err:  # bir hisse hata verse de diğerleri sürer
            failed[symbol] = str(err)
            print(f"[{i:>2}/{len(symbols)}] {symbol:<6} HATA: {err}")
        else:
            first, last = prices["date"].iloc[0], prices["date"].iloc[-1]
            print(f"[{i:>2}/{len(symbols)}] {symbol:<6} "
                  f"{len(prices):>4} satır  {first} -> {last}")
        time.sleep(WAIT_SECONDS)

    print(f"\nBaşarılı: {len(symbols) - len(failed)} | "
          f"Hatalı: {len(failed)}")
    if failed:
        print("Hatalıları tekrar denemek için:")
        print(f"  python data_collection\\fetch_prices.py "
              f"{' '.join(failed)}")


if __name__ == "__main__":
    main()
