"""
assign_trading_dates() fonksiyonunun testi (GAB İG-10).

Gerçek veritabanına dokunmaz: bellekte geçici bir veritabanı kurar.
Çalıştırma: python tests\\test_trading_dates.py
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent
                       / "data_collection"))

from database import assign_trading_dates, create_schema  # noqa: E402

# İşlem günleri: Çarşamba, Perşembe, (Cuma ve hafta sonu yok), Pazartesi
TRADING_DAYS = ["2026-11-04", "2026-11-05", "2026-11-09"]

# source_id -> (published_at, beklenen trading_date)
CASES = {
    "kapanis_oncesi": ("2026-11-04T10:00:00+03:00", "2026-11-04"),
    "kapanistan_1dk_once": ("2026-11-04T18:09:00+03:00", "2026-11-04"),
    "tam_kapanis": ("2026-11-04T18:10:00+03:00", "2026-11-05"),
    "aksam": ("2026-11-04T21:30:00+03:00", "2026-11-05"),
    "borsa_kapali_cuma": ("2026-11-06T11:00:00+03:00", "2026-11-09"),
    "hafta_sonu": ("2026-11-07T12:00:00+03:00", "2026-11-09"),
    "son_gunden_sonra": ("2026-11-09T19:00:00+03:00", None),
}


def make_db() -> sqlite3.Connection:
    """Şemayı ve örnek fiyatları içeren geçici bir veritabanı kurar."""
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    create_schema(conn)
    conn.execute("INSERT INTO stocks (symbol, yahoo_symbol) "
                 "VALUES ('THYAO', 'THYAO.IS')")
    conn.executemany(
        "INSERT INTO prices VALUES ('THYAO', ?, 10, 11, 9, 10, 10, 100)",
        [(day,) for day in TRADING_DAYS],
    )
    conn.executemany(
        "INSERT INTO contents (type, source, text, published_at, source_id) "
        "VALUES ('news', 'test', 'metin', ?, ?)",
        [(published, source_id)
         for source_id, (published, _) in CASES.items()],
    )
    return conn


def test_assign_trading_dates() -> None:
    conn = make_db()

    assigned, missing = assign_trading_dates(conn)
    assert assigned == 6, assigned
    assert missing == 1, missing

    rows = dict(conn.execute(
        "SELECT source_id, trading_date FROM contents").fetchall())
    for source_id, (_, expected) in CASES.items():
        assert rows[source_id] == expected, (source_id, rows[source_id])

    # İkinci çalıştırma hiçbir şeyi değiştirmemeli
    assert assign_trading_dates(conn) == (0, 1)

    # Yeni işlem günü gelince boş kalan içerik doldurulmalı
    conn.execute("INSERT INTO prices VALUES "
                 "('THYAO', '2026-11-10', 10, 11, 9, 10, 10, 100)")
    assert assign_trading_dates(conn) == (1, 0)
    late = conn.execute("SELECT trading_date FROM contents "
                        "WHERE source_id = 'son_gunden_sonra'").fetchone()[0]
    assert late == "2026-11-10", late


if __name__ == "__main__":
    test_assign_trading_dates()
    print("test_assign_trading_dates: BAŞARILI")
