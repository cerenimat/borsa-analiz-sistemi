"""
BIST 50 fiyat verisinin teyidi (Ceren'in "fiyat verisi teyidi" isteği).

Ham CSV dosyalarını okur (data/raw/<SEMBOL>_raw.csv) ve her hisse için:
  * ilk ve son işlem gününü, satır sayısını,
  * START_DATE'ten sonra başlayıp başlamadığını (sonradan halka arz),
  * borsa takvimine göre eksik ve fazla günleri,
  * temizleme kurallarının kaç satır sildiğini
raporlar. Hiçbir şeyi değiştirmez; raporu ekrana ve
data/processed/price_verification.csv dosyasına yazar.

Borsa takvimi: hisselerin en az yarısında bulunan tarihler.
"""

from datetime import datetime

import pandas as pd

from cleaning import clean_prices
from config import PROCESSED_DIR, START_DATE, STOCKS, TIMEZONE, raw_csv_path

REPORT_PATH = PROCESSED_DIR / "price_verification.csv"
MAX_DATES_SHOWN = 5  # eksik/fazla günlerden ekranda gösterilecek en fazla


def load_raw() -> dict[str, pd.DataFrame]:
    """Ham CSV'si olan hisseleri {sembol: tablo} olarak okur."""
    frames = {}
    for symbol in STOCKS:
        path = raw_csv_path(symbol)
        if path.exists():
            frames[symbol] = pd.read_csv(path, dtype={"date": str})
    return frames


def market_calendar(frames: dict[str, pd.DataFrame]) -> list[str]:
    """Hisselerin en az yarısında bulunan tarihleri borsa takvimi sayar."""
    counts = pd.concat([df["date"] for df in frames.values()]).value_counts()
    return sorted(counts[counts >= len(frames) / 2].index)


def first_trading_day(calendar: list[str]) -> str:
    """Takvimde START_DATE ve sonrasındaki ilk işlem günü (ör. 2023-01-02)."""
    return next(day for day in calendar if day >= START_DATE)


def verify_symbol(df: pd.DataFrame, calendar: list[str],
                  first_day: str, now: datetime) -> dict:
    """Bir hissenin teyit sonuçlarını sözlük olarak döndürür."""
    dates = set(df["date"])
    start, end = min(dates), max(dates)
    expected = {d for d in calendar if start <= d <= end}
    missing = sorted(expected - dates)
    extra = sorted(dates - set(calendar))
    _, report = clean_prices(df, now=now)

    notes = []
    if start > first_day:
        notes.append(f"{start} tarihinde başlıyor (sonradan halka arz?)")
    if missing:
        notes.append(f"{len(missing)} eksik gün")
    if extra:
        notes.append(f"{len(extra)} fazla gün")
    removed = report["silinen_toplam"] - report["yarim_gun"]
    if removed:
        notes.append(f"temizlemede {removed} satır silinir")

    return {
        "satir": len(df),
        "ilk_tarih": start,
        "son_tarih": end,
        "sonradan_baslayan": start > first_day,
        "eksik_gun": len(missing),
        "fazla_gun": len(extra),
        "temizlenen": removed,
        "durum": "UYARI" if notes else "TAMAM",
        "not": "; ".join(notes),
        "eksik_tarihler": " ".join(missing[:MAX_DATES_SHOWN]),
        "fazla_tarihler": " ".join(extra[:MAX_DATES_SHOWN]),
    }


def main() -> None:
    pd.set_option("display.width", 200)
    pd.set_option("display.max_colwidth", 60)

    frames = load_raw()
    if not frames:
        raise SystemExit("Ham veri yok. Önce fetch_prices.py çalışmalı.")
    calendar = market_calendar(frames)
    first_day = first_trading_day(calendar)
    now = datetime.now(TIMEZONE)

    rows = []
    for symbol, df in frames.items():
        result = verify_symbol(df, calendar, first_day, now)
        rows.append({"symbol": symbol, **result})
    report = pd.DataFrame(rows).sort_values(["durum", "symbol"],
                                            ascending=[False, True])

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    report.to_csv(REPORT_PATH, index=False, encoding="utf-8-sig")

    print(f"Borsa takvimi: {len(calendar)} işlem günü "
          f"({calendar[0]} -> {calendar[-1]})")
    print(f"Teyit edilen hisse: {len(frames)} / {len(STOCKS)}\n")

    warnings = report[report["durum"] == "UYARI"]
    print(f"=== UYARI ({len(warnings)} hisse) ===")
    if warnings.empty:
        print("Yok.")
    else:
        cols = ["symbol", "satir", "ilk_tarih", "not",
                "eksik_tarihler", "fazla_tarihler"]
        print(warnings[cols].to_string(index=False))

    ok = report[report["durum"] == "TAMAM"]["symbol"]
    print(f"\n=== TAMAM ({len(ok)} hisse) ===")
    print(" ".join(ok))
    print(f"\nRapor: {REPORT_PATH}")


if __name__ == "__main__":
    main()
