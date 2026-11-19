import argparse
import json
from pathlib import Path

import pandas as pd

from features import build_features
from models import LojistikRegresyonModeli, RastgeleOrmanModeli
from train import MODELS_DIR, get_all_symbols, time_series_split

PRICE_ONLY_FEATURES = [
    "daily_return",
    "ma_20",
    "ma_50",
    "volatility_20",
    "rsi_14",
]

SENTIMENT_FEATURES = [
    "news_score",
    "comment_score",
    "news_score_ma5",
    "comment_score_ma5",
]

ALL_FEATURES = PRICE_ONLY_FEATURES + SENTIMENT_FEATURES


def compare_for_symbol(symbol: str, train_ratio: float = 0.8) -> list[dict]:
    """Tek bir hisse için duygusuz (sadece fiyat) ve duygulu (fiyat+duygu) modelleri kıyaslar."""
    df = build_features(symbol)
    train_df, test_df = time_series_split(df, train_ratio=train_ratio)

    senaryolar = {
        "duygusuz": PRICE_ONLY_FEATURES,
        "duygulu": ALL_FEATURES,
    }

    sonuclar = []
    for senaryo_adi, ozellikler in senaryolar.items():
        x_train, y_train = train_df[ozellikler], train_df["target"]
        x_test, y_test = test_df[ozellikler], test_df["target"]

        for model in (LojistikRegresyonModeli(), RastgeleOrmanModeli()):
            model.egit(x_train, y_train)
            rapor = model.degerlendir(x_test, y_test)
            sonuclar.append(
                {
                    "symbol": symbol,
                    "senaryo": senaryo_adi,
                    "model": rapor["model"],
                    "accuracy": rapor["accuracy"],
                    "precision": rapor["precision"],
                    "recall": rapor["recall"],
                    "f1": rapor["f1"],
                }
            )

    symbol_dir = MODELS_DIR / symbol
    symbol_dir.mkdir(parents=True, exist_ok=True)
    with open(symbol_dir / "sentiment_comparison.json", "w", encoding="utf-8") as f:
        json.dump(sonuclar, f, ensure_ascii=False, indent=2)

    return sonuclar


def compare_all_stocks() -> None:
    """Tüm BIST 50 hisselerinde duygulu vs. duygusuz ortalama farkı hesaplar."""
    tum_satirlar = []
    for sym in get_all_symbols():
        tum_satirlar.extend(compare_for_symbol(sym))

    df = pd.DataFrame(tum_satirlar)
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(MODELS_DIR / "sentiment_comparison_bist50.csv", index=False, encoding="utf-8")

    ozet = df.groupby(["model", "senaryo"])[["accuracy", "f1"]].mean().round(4)
    print("\n=== BIST 50 Ortalama: Duygusuz vs. Duygulu (İG-23) ===")
    print(ozet)
    print("\nDetaylı tablo kaydedildi: models/sentiment_comparison_bist50.csv")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Duygulu vs. duygusuz özellik seti karşılaştırması.")
    parser.add_argument("--symbol", default="THYAO", help="Tek hisse sembolü")
    parser.add_argument("--all", action="store_true", help="Tüm BIST 50 için çalıştır")
    args = parser.parse_args()

    if args.all:
        compare_all_stocks()
    else:
        sonuc = compare_for_symbol(args.symbol.upper())
        print(f"\n=== {args.symbol.upper()} Duygusuz vs. Duygulu Karşılaştırması ===")
        print(pd.DataFrame(sonuc)[["model", "senaryo", "accuracy", "f1"]].to_string(index=False))