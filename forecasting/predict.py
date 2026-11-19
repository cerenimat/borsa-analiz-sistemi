import argparse
import json
from typing import Any

import joblib

from features import compute_rsi, load_raw_data
from train import FEATURE_COLUMNS, MODELS_DIR


def _prepare_latest_features(symbol: str):
    """Veritabanındaki en son işlem günü için özellik satırını hazırlar."""
    df = load_raw_data(symbol)
    df["daily_return"] = df["adj_close"].pct_change()
    df["ma_20"] = df["adj_close"].rolling(window=20).mean()
    df["ma_50"] = df["adj_close"].rolling(window=50).mean()
    df["volatility_20"] = df["daily_return"].rolling(window=20).std()
    df["rsi_14"] = compute_rsi(df["adj_close"], window=14)
    df["news_score_ma5"] = df["news_score"].rolling(window=5).mean()
    df["comment_score_ma5"] = df["comment_score"].rolling(window=5).mean()

    latest = df.dropna(subset=FEATURE_COLUMNS).iloc[[-1]]
    return latest


def predict_next_day(symbol: str) -> dict[str, Any]:
    """Kayıtlı modellerle bir sonraki işlem günü için yön ve olasılık tahmini üretir."""
    symbol = symbol.upper()
    symbol_dir = MODELS_DIR / symbol
    metrics_path = symbol_dir / "metrics.json"

    if not metrics_path.exists():
        raise FileNotFoundError(
            f"{symbol} için eğitilmiş model bulunamadı. Önce train.py çalıştırın."
        )

    latest_row = _prepare_latest_features(symbol)
    x_latest = latest_row[FEATURE_COLUMNS]
    son_tarih = str(latest_row["date"].iloc[0].date())

    tahminler = []
    for model_path in sorted(symbol_dir.glob("*.joblib")):
        model = joblib.load(model_path)
        if "cogunluk" in model_path.stem:
            continue

        sinif = int(model.tahmin_et(x_latest)[0])
        yukselis_olasiligi = float(model.olasilik_tahmin_et(x_latest)[0])
        guven = yukselis_olasiligi if sinif == 1 else (1.0 - yukselis_olasiligi)

        tahminler.append(
            {
                "model": model.ad,
                "yon": "Yükseliş" if sinif == 1 else "Düşüş",
                "olasilik": round(guven, 4),
            }
        )

    with open(metrics_path, "r", encoding="utf-8") as f:
        metrics = json.load(f)

    return {
        "symbol": symbol,
        "son_islem_gunu": son_tarih,
        "uyari": "Deneysel tahmindir; yatırım tavsiyesi değildir.",
        "tahminler": tahminler,
        "model_bilgisi": {
            "train_period": metrics["train_period"],
            "test_period": metrics["test_period"],
            "trained_at": metrics["trained_at"],
            "features": metrics["features"],
        },
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bir sonraki işlem günü yön tahmini üretir.")
    parser.add_argument("--symbol", default="THYAO", help="Hisse sembolü")
    args = parser.parse_args()

    sonuc = predict_next_day(args.symbol)
    print(json.dumps(sonuc, ensure_ascii=False, indent=2))
