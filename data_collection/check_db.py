"""
Veritabanının içeriğini kontrol eder (yalnızca okur, hiçbir şey yazmaz).

1. Tabloları, görünümleri ve kayıt sayılarını listeler.
2. Her hissenin tarih aralığını gösterir.
3. Veritabanındaki veriyi temiz CSV dosyalarıyla karşılaştırır.
4. Son güncelleme günlüğü kayıtlarını gösterir.
"""

import sqlite3
from contextlib import closing

import pandas as pd

from config import DB_PATH, STOCKS, clean_csv_path


def main() -> None:
    pd.set_option("display.width", 160)
    pd.set_option("display.max_columns", 20)

    if not DB_PATH.exists():
        raise FileNotFoundError(f"{DB_PATH} yok. Önce database.py çalışmalı.")

    with closing(sqlite3.connect(DB_PATH)) as conn:
        print("=== TABLOLAR VE GÖRÜNÜMLER ===")
        objects = conn.execute(
            "SELECT type, name FROM sqlite_master "
            "WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%' "
            "ORDER BY type, name"
        ).fetchall()
        for kind, name in objects:
            count = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
            print(f"{kind:<6} {name:<16}: {count} kayıt")

        print("\n=== HİSSE BAZINDA ÖZET ===")
        summary = pd.read_sql(
            """SELECT s.symbol, s.yahoo_symbol, COUNT(p.date) AS gun,
                      MIN(p.date) AS ilk_tarih, MAX(p.date) AS son_tarih
               FROM stocks s
               LEFT JOIN prices p ON p.symbol = s.symbol
               GROUP BY s.symbol, s.yahoo_symbol
               ORDER BY s.symbol""",
            conn,
        )
        with_prices = summary[summary["gun"] > 0]
        print(with_prices.to_string(index=False))
        print(f"Fiyatı henüz olmayan hisse: {len(summary) - len(with_prices)}")

        print("\n=== CSV İLE KARŞILAŞTIRMA ===")
        for symbol in STOCKS:
            if not clean_csv_path(symbol).exists():
                continue  # bu hisse için henüz fiyat yüklenmemiş
            db_prices = pd.read_sql(
                "SELECT * FROM prices WHERE symbol = ? ORDER BY date",
                conn, params=(symbol,),
            )
            csv_prices = pd.read_csv(clean_csv_path(symbol))
            for df in (db_prices, csv_prices):
                df["symbol"] = df["symbol"].astype(str)
                df["date"] = df["date"].astype(str)
            same = db_prices.equals(csv_prices)
            print(f"{symbol:<6} veritabanı: {len(db_prices)} | "
                  f"CSV: {len(csv_prices)} | "
                  f"birebir aynı mı? {'EVET' if same else 'HAYIR'}")

        print("\n=== GÜNCELLEME GÜNLÜĞÜ (son 5) ===")
        log = pd.read_sql(
            "SELECT id, source, symbol, run_at, status, input_rows, "
            "removed, inserted, existing FROM update_log "
            "ORDER BY id DESC LIMIT 5", conn
        )
        print(log.to_string(index=False))


if __name__ == "__main__":
    main()
