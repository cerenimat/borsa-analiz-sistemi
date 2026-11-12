"""
Ortak veritabanındaki fiyatları günceller (Faz 4, GAB İG-05).

fetch_prices.py tüm geçmişi baştan çeker. Bu betik ise her hisse için
yalnızca veritabanındaki son tarihten bu yana olan günleri çeker:

  1. Her hissenin son tarihi bulunur.
  2. Son tarihten OVERLAP_DAYS gün öncesinden başlayarak veri çekilir.
     Örtüşen günler, Yahoo'nun sonradan düzelttiği değerleri ve
     temettüyü yakalamak içindir.
  3. Örtüşen günlerin adj_close değeri veritabanındakiyle tutmuyorsa
     (yeni temettü veya bölünme) hisse START_DATE'ten baştan çekilir.
  4. Veri temizlenir, kaydedilir ve update_log'a yazılır.
  5. En sonda içeriklerin işlem günleri atanır.

Kullanım:
  python data_collection\\update.py
"""

import sqlite3
import time
from datetime import date, timedelta

import pandas as pd

from cleaning import clean_prices
from config import DB_PATH, START_DATE, STOCKS
from database import (assign_trading_dates, connect, save_prices,
                      seed_stocks, write_log)
from fetch_prices import WAIT_SECONDS, fetch_raw, standardize

OVERLAP_DAYS = 7   # son tarihten kaç takvim günü geriden başlanacağı
ADJ_TOLERANCE = 1e-4  # adj_close'ta göze alınan göreli fark (%0,01)


def last_dates(conn: sqlite3.Connection) -> dict[str, str]:
    """Her hissenin veritabanındaki son fiyat tarihini döndürür.

    Örnek: {"THYAO": "2026-11-10", "GLRMK": "2026-11-10", ...}
    Hiç fiyatı olmayan hisse sözlükte yer almaz.
    """
    rows = conn.execute(
        "SELECT symbol, MAX(date) FROM prices GROUP BY symbol"
    ).fetchall()
    return dict(rows)


def fetch_recent(symbol: str, last_date: str) -> tuple[pd.DataFrame, dict]:
    """Son tarihten OVERLAP_DAYS gün öncesinden bugüne kadar olan veriyi
    çeker ve temizler; (temiz_tablo, temizleme_raporu) döndürür."""
    start = date.fromisoformat(last_date) - timedelta(days=OVERLAP_DAYS)
    raw = standardize(fetch_raw(symbol, start.isoformat()), symbol)
    return clean_prices(raw)


def adj_close_changed(conn: sqlite3.Connection, symbol: str,
                      clean: pd.DataFrame) -> bool:
    """Örtüşen günlerden birinde adj_close veritabanındakinden farklıysa
    True döner (yeni temettü veya bölünme: geçmiş yeniden düzeltilmiş)."""
    stored = dict(conn.execute(
        "SELECT date, adj_close FROM prices WHERE symbol = ? AND date >= ?",
        (symbol, clean["date"].min()),
    ).fetchall())
    for day, new in zip(clean["date"], clean["adj_close"]):
        old = stored.get(day)
        if old is not None and abs(new - old) > ADJ_TOLERANCE * old:
            return True
    return False


def update_symbol(conn: sqlite3.Connection, symbol: str,
                  last_date: str | None) -> tuple[str, int, int]:
    """Bir hissenin fiyatlarını günceller; (mod, yeni, var_olan) döndürür.

    mod "artimli": yalnızca son günler çekildi.
    mod "tam": hisse START_DATE'ten baştan çekildi (yeni hisse ya da temettü).
    """
    mode = "artimli"
    if last_date is None:          # veritabanında hiç fiyatı yok
        mode = "tam"
    else:
        clean, report = fetch_recent(symbol, last_date)
        if adj_close_changed(conn, symbol, clean):
            mode = "tam"
    if mode == "tam":
        raw = standardize(fetch_raw(symbol, START_DATE), symbol)
        clean, report = clean_prices(raw)

    inserted, existing = save_prices(conn, clean, symbol)
    report["mod"] = mode
    write_log(conn, symbol, "success", report, inserted, existing)
    return mode, inserted, existing


def main() -> None:
    conn = connect(DB_PATH)
    try:
        seed_stocks(conn)   # JSON'a yeni hisse eklendiyse stocks'a girsin
        dates = last_dates(conn)
        modes = {"artimli": 0, "tam": 0}
        failed = []
        total = len(STOCKS)
        for i, symbol in enumerate(STOCKS, start=1):
            try:
                mode, inserted, existing = update_symbol(
                    conn, symbol, dates.get(symbol))
            except Exception as err:  # bir hisse hata verse de diğerleri sürer
                failed.append(symbol)
                write_log(conn, symbol, "error", {"hata": str(err)})
                print(f"[{i:>2}/{total}] {symbol:<6} HATA: {err}")
            else:
                modes[mode] += 1
                print(f"[{i:>2}/{total}] {symbol:<6} {mode:<8} "
                      f"yeni: {inserted:>4} | güncellenen: {existing:>4}")
            time.sleep(WAIT_SECONDS)
        assigned, missing = assign_trading_dates(conn)
    finally:
        conn.close()

    print(f"\nArtımlı: {modes['artimli']} | Tam: {modes['tam']} | "
          f"Hatalı: {len(failed)}")
    print(f"İşlem günü atanan içerik: {assigned} | boş kalan: {missing}")
    if failed:
        print("Hatalı hisseler tekrar çalıştırmada yeniden denenir: "
              + " ".join(failed))


if __name__ == "__main__":
    main()
