"""
Veritabanını schema.sql'e göre oluşturur ve config.STOCKS içindeki
hisselerin temiz fiyat verisini kaydeder (GAB İG-04, İOG-G-04).

Akış (her hisse için):
  data/raw/<SEMBOL>_raw.csv -> clean_prices()
      -> stocks + prices tabloları
      -> data/processed/<SEMBOL>_clean.csv
      -> update_log tablosu
"""

import json
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

import pandas as pd

from cleaning import clean_prices
from config import (DB_PATH, PROCESSED_DIR, SCHEMA_PATH, STOCKS, TIMEZONE,
                    clean_csv_path, raw_csv_path, yahoo_symbol)

# Aynı (symbol, date) zaten varsa satırı güncelle: yeni bir temettü
# geldiğinde yfinance geçmiş adj_close değerlerini değiştirir.
UPSERT_PRICE = """
INSERT INTO prices (symbol, date, open, high, low, close, adj_close, volume)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (symbol, date) DO UPDATE SET
    open = excluded.open,
    high = excluded.high,
    low = excluded.low,
    close = excluded.close,
    adj_close = excluded.adj_close,
    volume = excluded.volume
"""

UPSERT_STOCK = """
INSERT INTO stocks (symbol, name, yahoo_symbol) VALUES (?, ?, ?)
ON CONFLICT (symbol) DO UPDATE SET
    name = excluded.name,
    yahoo_symbol = excluded.yahoo_symbol
"""

PRICE_COLUMNS = ["symbol", "date", "open", "high", "low",
                 "close", "adj_close", "volume"]


def connect(db_path: Path) -> sqlite3.Connection:
    """Veritabanına bağlanır; yabancı anahtar kontrolünü açar."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def create_schema(conn: sqlite3.Connection) -> None:
    """schema.sql'deki tabloları ve görünümleri oluşturur (varsa dokunmaz)."""
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))


def count_prices(conn: sqlite3.Connection, symbol: str) -> int:
    """Bir hissenin veritabanındaki fiyat kaydı sayısını döndürür."""
    row = conn.execute(
        "SELECT COUNT(*) FROM prices WHERE symbol = ?", (symbol,)
    ).fetchone()
    return row[0]


def save_prices(conn: sqlite3.Connection, prices: pd.DataFrame,
                symbol: str, name: str) -> tuple[int, int]:
    """Hisseyi ve fiyatlarını kaydeder; (yeni_eklenen, zaten_var) döndürür."""
    rows = [
        (r.symbol, r.date, float(r.open), float(r.high), float(r.low),
         float(r.close), float(r.adj_close), int(r.volume))
        for r in prices[PRICE_COLUMNS].itertuples(index=False)
    ]
    before = count_prices(conn, symbol)
    with conn:  # hepsi kaydedilir ya da hiçbiri (transaction)
        conn.execute(UPSERT_STOCK, (symbol, name, yahoo_symbol(symbol)))
        conn.executemany(UPSERT_PRICE, rows)
    inserted = count_prices(conn, symbol) - before
    return inserted, len(rows) - inserted


def write_log(conn: sqlite3.Connection, symbol: str, status: str,
              report: dict, inserted: int | None = None,
              existing: int | None = None) -> None:
    """Çalıştırmanın özetini update_log tablosuna yazar."""
    run_at = datetime.now(TIMEZONE).isoformat(timespec="seconds")
    with conn:
        conn.execute(
            """INSERT INTO update_log
               (source, symbol, run_at, status, input_rows, removed,
                inserted, existing, detail)
               VALUES ('yfinance', ?, ?, ?, ?, ?, ?, ?, ?)""",
            (symbol, run_at, status, report.get("girdi_satir"),
             report.get("silinen_toplam"), inserted, existing,
             json.dumps(report, ensure_ascii=False)),
        )


def load_symbol(conn: sqlite3.Connection, symbol: str, name: str) -> None:
    """Bir hissenin ham CSV'sini temizleyip veritabanına yükler."""
    report: dict = {}
    try:
        clean, report = clean_prices(pd.read_csv(raw_csv_path(symbol)))
        clean.to_csv(clean_csv_path(symbol), index=False, encoding="utf-8")
        inserted, existing = save_prices(conn, clean, symbol, name)
    except Exception as err:  # bir hisse hata verirse diğerleri devam etsin
        report["hata"] = str(err)
        write_log(conn, symbol, "error", report)
        print(f"{symbol:<6} HATA: {err}")
        return
    write_log(conn, symbol, "success", report, inserted, existing)
    print(f"{symbol:<6} temizlenen: {report['silinen_toplam']:>4} | "
          f"yeni: {inserted:>5} | zaten vardı: {existing:>5} | "
          f"toplam: {count_prices(conn, symbol)}")


def main() -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    with closing(connect(DB_PATH)) as conn:
        create_schema(conn)
        for symbol, name in STOCKS.items():
            load_symbol(conn, symbol, name)
    print(f"\nVeritabanı: {DB_PATH}")


if __name__ == "__main__":
    main()
