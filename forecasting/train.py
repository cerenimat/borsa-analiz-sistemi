import argparse
import json
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

import joblib
import pandas as pd

from features import DB_PATH, build_features
from models import (
    CogunlukSinifiModeli,
    LojistikRegresyonModeli,
    RastgeleOrmanModeli,
    TahminModeli,
)

FEATURE_COLUMNS = [
    "daily_return",
    "ma_20",
    "ma_50",
    "volatility_20",
    "rsi_14",
    "news_score",
    "comment_score",
    "news_score_ma5",
    "comment_score_ma5",
]

MODELS_DIR = Path("models")


def get_all_symbols(db_path: Path = DB_PATH) -> list[str]:
    """Veritabanındaki tüm hisse sembollerini alfabetik olarak döndürür."""
    with closing(sqlite3.connect(db_path)) as conn:
        rows = conn.execute("SELECT symbol FROM stocks ORDER BY symbol;").fetchall()
    return [r[0] for r in rows]


def time_series_split(
    df: pd.DataFrame, train_ratio: float = 0.8
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Veriyi karıştırmadan zaman sırasıyla eğitim ve test kümelerine ayırır (İG-17)."""
    split_idx = int(len(df) * train_ratio)
    train_df = df.iloc[:split_idx].copy()
    test_df = df.iloc[split_idx:].copy()

    # Veri sızıntısı kontrolü (İOG-G-03)
    assert train_df["date"].max() < test_df["date"].min(), "Veri sızıntısı tespit edildi!"
    return train_df, test_df


def train_and_evaluate(symbol: str, train_ratio: float = 0.8) -> dict:
    """Seçilen hisse için tüm modelleri eğitir, değerlendirir ve kaydeder."""
    df = build_features(symbol)
    train_df, test_df = time_series_split(df, train_ratio=train_ratio)

    x_train, y_train = train_df[FEATURE_COLUMNS], train_df["target"]
    x_test, y_test = test_df[FEATURE_COLUMNS], test_df["target"]

    modeller: list[TahminModeli] = [
        CogunlukSinifiModeli(),
        LojistikRegresyonModeli(),
        RastgeleOrmanModeli(),
    ]

    symbol_dir = MODELS_DIR / symbol
    symbol_dir.mkdir(parents=True, exist_ok=True)

    sonuclar = []
    gunluk_tahminler = {
        "symbol": symbol,
        "dates": [str(d.date()) for d in test_df["date"]],
        "actual": [int(v) for v in y_test],
        "predictions": {},
    }

    for m in modeller:
        m.egit(x_train, y_train)
        rapor = m.degerlendir(x_test, y_test)
        sonuclar.append(rapor)

        # İG-22: Test dönemi tahmin-gerçekleşen grafiği için günlük çıktılar
        gunluk_tahminler["predictions"][m.ad] = [int(v) for v in m.tahmin_et(x_test)]

        dosya_adi = m.ad.lower().replace(" ", "_").replace("(", "").replace(")", "") + ".joblib"
        joblib.dump(m, symbol_dir / dosya_adi)

    ozet = {
        "symbol": symbol,
        "trained_at": datetime.now().isoformat(timespec="seconds"),
        "features": FEATURE_COLUMNS,
        "train_period": [
            str(train_df["date"].min().date()),
            str(train_df["date"].max().date()),
        ],
        "test_period": [
            str(test_df["date"].min().date()),
            str(test_df["date"].max().date()),
        ],
        "train_size": len(train_df),
        "test_size": len(test_df),
        "results": sonuclar,
    }

    with open(symbol_dir / "metrics.json", "w", encoding="utf-8") as f:
        json.dump(ozet, f, ensure_ascii=False, indent=2)

    with open(symbol_dir / "test_predictions.json", "w", encoding="utf-8") as f:
        json.dump(gunluk_tahminler, f, ensure_ascii=False, indent=2)

    return ozet


def train_all_stocks(train_ratio: float = 0.8) -> None:
    """BIST 50'deki tüm hisseleri sırayla eğitir ve genel özet kaydeder."""
    symbols = get_all_symbols()
    tum_sonuclar = []
    hatali = []

    print(f"Toplam {len(symbols)} hisse için toplu eğitim başlıyor...\n")
    for idx, sym in enumerate(symbols, start=1):
        try:
            rapor = train_and_evaluate(sym, train_ratio=train_ratio)
            satir = {"symbol": sym, "test_size": rapor["test_size"]}
            for r in rapor["results"]:
                satir[f"{r['model']}_acc"] = r["accuracy"]
                satir[f"{r['model']}_f1"] = r["f1"]
            tum_sonuclar.append(satir)
            print(f"[{idx:02d}/{len(symbols)}] {sym:<6} tamamlandı (test: {rapor['test_size']} gün)")
        except Exception as exc:
            hatali.append({"symbol": sym, "error": str(exc)})
            print(f"[{idx:02d}/{len(symbols)}] {sym:<6} HATA: {exc}")

    summary_df = pd.DataFrame(tum_sonuclar)
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    summary_df.to_csv(MODELS_DIR / "bist50_summary.csv", index=False, encoding="utf-8")

    print("\n=== BIST 50 Ortalama Performans ===")
    for col in summary_df.columns:
        if col.endswith("_acc") or col.endswith("_f1"):
            print(f"{col:<35}: {summary_df[col].mean():.4f}")

    if hatali:
        print(f"\nHata alınan hisseler ({len(hatali)}): {hatali}")
    print("\nÖzet tablo kaydedildi: models/bist50_summary.csv")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Hisse yön tahmin modellerini eğitir.")
    parser.add_argument("--symbol", default="THYAO", help="Tek hisse sembolü (ör. THYAO)")
    parser.add_argument("--all", action="store_true", help="Tüm BIST 50 hisselerini eğit")
    args = parser.parse_args()

    if args.all:
        train_all_stocks()
    else:
        rapor = train_and_evaluate(args.symbol.upper())
        print(f"\n=== {rapor['symbol']} Model Değerlendirme Sonuçları ===")
        print(f"Eğitim: {rapor['train_period'][0]} -> {rapor['train_period'][1]} ({rapor['train_size']} gün)")
        print(f"Test  : {rapor['test_period'][0]} -> {rapor['test_period'][1]} ({rapor['test_size']} gün)\n")

        tablo = pd.DataFrame(
            [
                {
                    "Model": r["model"],
                    "Doğruluk": r["accuracy"],
                    "Kesinlik": r["precision"],
                    "Duyarlılık": r["recall"],
                    "F1": r["f1"],
                }
                for r in rapor["results"]
            ]
        )
        print(tablo.to_string(index=False))
        print(f"\nModeller ve metrics.json kaydedildi: models/{rapor['symbol']}/")