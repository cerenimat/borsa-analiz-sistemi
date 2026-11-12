"""
update.py'deki adj_close_changed() fonksiyonunun testi (Faz 4).

Gerçek veritabanına ve internete dokunmaz: bellekte geçici bir
veritabanı kurar, Yahoo'dan gelmiş gibi sahte tablolar verir.
Çalıştırma: python tests\\test_update.py
"""

import sqlite3
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent
                       / "data_collection"))

from database import create_schema  # noqa: E402
from update import adj_close_changed  # noqa: E402

# Veritabanında kayıtlı günler ve adj_close değerleri
STORED = {"2026-11-05": 100.0, "2026-11-06": 101.0, "2026-11-09": 102.0}


def make_db() -> sqlite3.Connection:
    """THYAO için üç günlük fiyat içeren geçici bir veritabanı kurar."""
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    create_schema(conn)
    conn.execute("INSERT INTO stocks (symbol, yahoo_symbol) "
                 "VALUES ('THYAO', 'THYAO.IS')")
    conn.executemany(
        "INSERT INTO prices VALUES ('THYAO', ?, 10, 11, 9, 10, ?, 100)",
        list(STORED.items()),
    )
    return conn


def fetched(values: dict[str, float]) -> pd.DataFrame:
    """Yahoo'dan gelmiş gibi {tarih: adj_close} tablosu."""
    return pd.DataFrame({"date": list(values),
                         "adj_close": list(values.values())})


def test_adj_close_changed() -> None:
    conn = make_db()

    # 1. Örtüşen günler aynı, yeni bir gün eklenmiş -> değişmedi
    same = {**STORED, "2026-11-10": 103.0}
    assert not adj_close_changed(conn, "THYAO", fetched(same))

    # 2. Yuvarlama kadar küçük fark (%0,001) -> değişmedi
    tiny = {day: value * 1.00001 for day, value in STORED.items()}
    assert not adj_close_changed(conn, "THYAO", fetched(tiny))

    # 3. Temettü: geçmiş adj_close %2 düşmüş -> değişti
    dividend = {day: value * 0.98 for day, value in STORED.items()}
    assert adj_close_changed(conn, "THYAO", fetched(dividend))

    # 4. Yalnızca tek bir örtüşen gün farklı -> değişti
    one_day = {**STORED, "2026-11-06": 99.0}
    assert adj_close_changed(conn, "THYAO", fetched(one_day))

    # 5. Hiç örtüşen gün yok (yalnızca yeni günler) -> değişmedi
    only_new = {"2026-11-10": 103.0, "2026-11-11": 104.0}
    assert not adj_close_changed(conn, "THYAO", fetched(only_new))

    # 6. Veritabanında hiç fiyatı olmayan hisse -> değişmedi
    assert not adj_close_changed(conn, "ASELS", fetched(same))


if __name__ == "__main__":
    test_adj_close_changed()
    print("test_adj_close_changed: BAŞARILI")
