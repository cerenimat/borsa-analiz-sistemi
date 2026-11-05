"""
SQLite veritabanını oluşturur ve temiz fiyat verisini kaydeder
(GAB İG-04, İOG-G-04).

Akış: data/raw/<SEMBOL>_raw.csv -> clean_prices() -> data/borsa.db

Tablolar:
  hisse              : desteklenen hisseler (GAB nesne modeli: Hisse)
  fiyat_kaydi        : günlük OHLCV kayıtları (GAB: FiyatKaydı)
  guncelleme_gunlugu : her çalıştırmanın özeti ve temizleme raporu
"""

import json
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from cleaning import clean_prices

SYMBOL = "THYAO.IS"
SYMBOL_NAME = "Türk Hava Yolları"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw"
DB_PATH = PROJECT_ROOT / "data" / "borsa.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS hisse (
    symbol   TEXT PRIMARY KEY,
    name     TEXT,
    exchange TEXT NOT NULL DEFAULT 'BIST',
    currency TEXT NOT NULL DEFAULT 'TRY'
);

CREATE TABLE IF NOT EXISTS fiyat_kaydi (
    symbol    TEXT    NOT NULL REFERENCES hisse(symbol),
    date      TEXT    NOT NULL
              CHECK (date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    open      REAL    NOT NULL CHECK (open > 0),
    high      REAL    NOT NULL CHECK (high > 0),
    low       REAL    NOT NULL CHECK (low > 0),
    close     REAL    NOT NULL CHECK (close > 0),
    adj_close REAL    NOT NULL CHECK (adj_close > 0),
    volume    INTEGER NOT NULL CHECK (volume >= 0),
    CHECK (low <= open AND open <= high AND low <= close AND close <= high),
    PRIMARY KEY (symbol, date)
);

CREATE TABLE IF NOT EXISTS guncelleme_gunlugu (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol      TEXT    NOT NULL,
    run_at      TEXT    NOT NULL,
    status      TEXT    NOT NULL CHECK (status IN ('BASARILI', 'HATA')),
    input_rows  INTEGER,
    removed     INTEGER,
    inserted    INTEGER,
    existing    INTEGER,
    detail      TEXT
);
"""

# Aynı (symbol, date) zaten varsa satırı güncelle: yeni bir temettü
# geldiğinde yfinance geçmiş adj_close değerlerini değiştirir.
UPSERT_PRICE = """
INSERT INTO fiyat_kaydi
    (symbol, date, open, high, low, close, adj_close, volume)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (symbol, date) DO UPDATE SET
    open = excluded.open,
    high = excluded.high,
    low = excluded.low,
    close = excluded.close,
    adj_close = excluded.adj_close,
    volume = excluded.volume
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
    """Tablolar yoksa oluşturur; varsa dokunmaz."""
    conn.executescript(SCHEMA)


def count_prices(conn: sqlite3.Connection, symbol: str) -> int:
    """Bir hissenin veritabanındaki kayıt sayısını döndürür."""
    row = conn.execute(
        "SELECT COUNT(*) FROM fiyat_kaydi WHERE symbol = ?", (symbol,)
    ).fetchone()
    return row[0]


def save_prices(conn: sqlite3.Connection, prices: pd.DataFrame,
                symbol: str, name: str) -> tuple[int, int]:
    """Fiyatları kaydeder; (yeni_eklenen, zaten_var_olan) döndürür."""
    rows = [
        (r.symbol, r.date, float(r.open), float(r.high), float(r.low),
         float(r.close), float(r.adj_close), int(r.volume))
        for r in prices[PRICE_COLUMNS].itertuples(index=False)
    ]
    before = count_prices(conn, symbol)
    with conn:  # hepsi kaydedilir ya da hiçbiri (transaction)
        conn.execute(
            "INSERT OR IGNORE INTO hisse (symbol, name) VALUES (?, ?)",
            (symbol, name),
        )
        conn.executemany(UPSERT_PRICE, rows)
    inserted = count_prices(conn, symbol) - before
    return inserted, len(rows) - inserted


def write_log(conn: sqlite3.Connection, symbol: str, status: str,
              report: dict, inserted: int | None = None,
              existing: int | None = None) -> None:
    """Çalıştırmanın özetini guncelleme_gunlugu tablosuna yazar."""
    run_at = datetime.now(ZoneInfo("Europe/Istanbul"))
    with conn:
        conn.execute(
            """INSERT INTO guncelleme_gunlugu
               (symbol, run_at, status, input_rows, removed,
                inserted, existing, detail)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (symbol, run_at.isoformat(timespec="seconds"), status,
             report.get("girdi_satir"), report.get("silinen_toplam"),
             inserted, existing, json.dumps(report, ensure_ascii=False)),
        )


def main() -> None:
    input_path = RAW_DIR / f"{SYMBOL.replace('.', '_')}_raw.csv"
    if not input_path.exists():
        raise FileNotFoundError(
            f"{input_path} bulunamadı. Önce fetch_prices.py çalıştırılmalı.")

    with closing(connect(DB_PATH)) as conn:
        create_schema(conn)
        report: dict = {}
        try:
            clean, report = clean_prices(pd.read_csv(input_path))
            inserted, existing = save_prices(conn, clean, SYMBOL,
                                             SYMBOL_NAME)
        except Exception as err:
            report["hata"] = str(err)
            write_log(conn, SYMBOL, "HATA", report)
            raise
        write_log(conn, SYMBOL, "BASARILI", report, inserted, existing)
        total = count_prices(conn, SYMBOL)

    print(f"Veritabanı      : {DB_PATH}")
    print(f"Temizlenen satır: {report['silinen_toplam']}")
    print(f"Yeni eklenen    : {inserted}")
    print(f"Zaten vardı     : {existing}")
    print(f"Toplam kayıt    : {total} ({SYMBOL})")


if __name__ == "__main__":
    main()