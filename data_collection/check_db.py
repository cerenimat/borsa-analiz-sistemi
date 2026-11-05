"""
Veritabanının içeriğini kontrol eder (yalnızca okur, hiçbir şey yazmaz).

1. Tabloları ve kayıt sayılarını listeler.
2. Her hissenin tarih aralığını gösterir.
3. Veritabanındaki veriyi temiz CSV ile karşılaştırır.
4. Son güncelleme günlüğü kayıtlarını gösterir.
"""

import sqlite3
from contextlib import closing
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "borsa.db"
CLEAN_CSV = PROJECT_ROOT / "data" / "processed" / "THYAO_IS_clean.csv"


def main() -> None:
    pd.set_option("display.width", 160)
    pd.set_option("display.max_columns", 20)

    if not DB_PATH.exists():
        raise FileNotFoundError(f"{DB_PATH} yok. Önce database.py çalışmalı.")

    with closing(sqlite3.connect(DB_PATH)) as conn:
        print("=== TABLOLAR ===")
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        for (name,) in tables:
            count = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
            print(f"{name:<20}: {count} kayıt")

        print("\n=== HİSSE BAZINDA ÖZET ===")
        summary = pd.read_sql(
            """SELECT h.symbol, h.name, COUNT(f.date) AS gun,
                      MIN(f.date) AS ilk_tarih, MAX(f.date) AS son_tarih
               FROM hisse h
               LEFT JOIN fiyat_kaydi f ON f.symbol = h.symbol
               GROUP BY h.symbol, h.name""",
            conn,
        )
        print(summary.to_string(index=False))

        print("\n=== SON 3 GÜN ===")
        last = pd.read_sql(
            "SELECT * FROM fiyat_kaydi ORDER BY date DESC LIMIT 3", conn
        )
        print(last.to_string(index=False))

        print("\n=== CSV İLE KARŞILAŞTIRMA ===")
        db_prices = pd.read_sql(
            "SELECT * FROM fiyat_kaydi WHERE symbol = 'THYAO.IS' "
            "ORDER BY date", conn
        )
        csv_prices = pd.read_csv(CLEAN_CSV)
        csv_prices["symbol"] = csv_prices["symbol"].astype(str)
        db_prices["symbol"] = db_prices["symbol"].astype(str)
        same = db_prices.reset_index(drop=True).equals(
            csv_prices.reset_index(drop=True))
        print(f"Veritabanı satırı: {len(db_prices)}")
        print(f"CSV satırı       : {len(csv_prices)}")
        print(f"Birebir aynı mı? : {'EVET' if same else 'HAYIR'}")

        print("\n=== GÜNCELLEME GÜNLÜĞÜ ===")
        log = pd.read_sql(
            "SELECT id, run_at, status, input_rows, removed, inserted, "
            "existing FROM guncelleme_gunlugu ORDER BY id", conn
        )
        print(log.to_string(index=False))


if __name__ == "__main__":
    main()