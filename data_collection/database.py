"""
Veritabanını schema.sql'e göre oluşturur ve config.STOCKS içindeki
hisselerin temiz fiyat verisini kaydeder (GAB İG-04, İOG-G-04).

Akış:
  1. config/bist50_oid.json -> stocks tablosu (50 hisse, KAP kimlikleriyle)
  2. Her hisse için: data/raw/<SEMBOL>_raw.csv -> clean_prices()
       -> prices tablosu, data/processed/<SEMBOL>_clean.csv, update_log
     (ham CSV'si olmayan hisse atlanır)
  3. contents tablosundaki boş trading_date alanları doldurulur
"""

import json
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

import pandas as pd

from cleaning import clean_prices
from config import (CONTENT_CUTOFF, DB_PATH, PROCESSED_DIR, SCHEMA_PATH,
                    STOCKS, TIMEZONE, clean_csv_path, load_stocks,
                    raw_csv_path, yahoo_symbol)

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
INSERT INTO stocks (symbol, name, yahoo_symbol, kap_oid) VALUES (?, ?, ?, ?)
ON CONFLICT (symbol) DO UPDATE SET
    name = excluded.name,
    yahoo_symbol = excluded.yahoo_symbol,
    kap_oid = excluded.kap_oid
"""

# Boş trading_date alanlarını doldurur (GAB İG-10):
#   * Kapanış saatinden önce yayımlanan içerik -> aynı gün (işlem günüyse)
#   * Kapanıştan sonra, hafta sonu veya bayramda -> sonraki ilk işlem günü
#   * Fiyat tablosunda henüz sonraki işlem günü yoksa -> boş kalır
ASSIGN_TRADING_DATES = """
UPDATE contents
SET trading_date = (
    SELECT MIN(t.date)
    FROM trading_days t
    WHERE t.date > substr(contents.published_at, 1, 10)
       OR (t.date = substr(contents.published_at, 1, 10)
           AND substr(contents.published_at, 12, 5) < ?)
)
WHERE trading_date IS NULL
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


def seed_stocks(conn: sqlite3.Connection) -> int:
    """stocks tablosunu config/bist50_oid.json dosyasından doldurur.

    Fiyat verisi olmasa da çalışır; böylece KAP verisi fiyatsız bir
    veritabanına da yüklenebilir (content_symbols -> stocks bağlantısı).
    """
    rows = [(s["symbol"], s["name"], yahoo_symbol(s["symbol"]), s["kap_oid"])
            for s in load_stocks()]
    with conn:
        conn.executemany(UPSERT_STOCK, rows)
    return len(rows)


def count_prices(conn: sqlite3.Connection, symbol: str) -> int:
    """Bir hissenin veritabanındaki fiyat kaydı sayısını döndürür."""
    row = conn.execute(
        "SELECT COUNT(*) FROM prices WHERE symbol = ?", (symbol,)
    ).fetchone()
    return row[0]


def save_prices(conn: sqlite3.Connection, prices: pd.DataFrame,
                symbol: str) -> tuple[int, int]:
    """Fiyatları kaydeder; (yeni_eklenen, zaten_var) döndürür.

    Hisse önceden stocks tablosunda olmalıdır (seed_stocks).
    """
    rows = [
        (r.symbol, r.date, float(r.open), float(r.high), float(r.low),
         float(r.close), float(r.adj_close), int(r.volume))
        for r in prices[PRICE_COLUMNS].itertuples(index=False)
    ]
    before = count_prices(conn, symbol)
    with conn:  # hepsi kaydedilir ya da hiçbiri (transaction)
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


def count_missing_trading_dates(conn: sqlite3.Connection) -> int:
    """trading_date alanı boş olan içerik sayısını döndürür."""
    row = conn.execute(
        "SELECT COUNT(*) FROM contents WHERE trading_date IS NULL"
    ).fetchone()
    return row[0]


def assign_trading_dates(conn: sqlite3.Connection) -> tuple[int, int]:
    """Boş trading_date alanlarını doldurur; (doldurulan, boş_kalan) döndürür.

    Fiyatlar güncellendikten sonra ve içerik yüklendikten sonra çağrılır.
    Tekrar çalıştırmak güvenlidir: yalnızca boş alanlara dokunur.
    """
    before = count_missing_trading_dates(conn)
    with conn:
        conn.execute(ASSIGN_TRADING_DATES, (CONTENT_CUTOFF,))
    after = count_missing_trading_dates(conn)
    return before - after, after


def load_symbol(conn: sqlite3.Connection, symbol: str) -> bool:
    """Bir hissenin ham CSV'sini temizleyip yükler; yüklendiyse True döner."""
    if not raw_csv_path(symbol).exists():
        return False  # bu hisse için henüz fiyat çekilmemiş
    report: dict = {}
    try:
        clean, report = clean_prices(pd.read_csv(raw_csv_path(symbol)))
        clean.to_csv(clean_csv_path(symbol), index=False, encoding="utf-8")
        inserted, existing = save_prices(conn, clean, symbol)
    except Exception as err:  # bir hisse hata verirse diğerleri devam etsin
        report["hata"] = str(err)
        write_log(conn, symbol, "error", report)
        print(f"{symbol:<6} HATA: {err}")
        return True
    write_log(conn, symbol, "success", report, inserted, existing)
    print(f"{symbol:<6} temizlenen: {report['silinen_toplam']:>4} | "
          f"yeni: {inserted:>5} | zaten vardı: {existing:>5} | "
          f"toplam: {count_prices(conn, symbol)}")
    return True


def main() -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    with closing(connect(DB_PATH)) as conn:
        create_schema(conn)
        print(f"stocks tablosu: {seed_stocks(conn)} hisse\n")
        skipped = [symbol for symbol in STOCKS
                   if not load_symbol(conn, symbol)]
        assigned, missing = assign_trading_dates(conn)
    if skipped:
        print(f"\nHam verisi olmadığı için atlanan: {len(skipped)} hisse")
    print(f"İşlem günü atanan içerik: {assigned} | boş kalan: {missing}")
    print(f"Veritabanı: {DB_PATH}")


if __name__ == "__main__":
    main()
