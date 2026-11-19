import sqlite3
from contextlib import closing
from pathlib import Path

import numpy as np
import pandas as pd

DB_PATH = Path("data") / "borsa.db"


def load_raw_data(symbol: str, db_path: Path = DB_PATH) -> pd.DataFrame:
    """Seçilen hisse için fiyat ve günlük duygu verilerini birleştirir."""
    query = """
    SELECT
        p.date,
        p.adj_close,
        p.volume,
        COALESCE(d.news_avg_score, 0.0) AS news_score,
        COALESCE(d.news_count, 0) AS news_count,
        COALESCE(d.comment_avg_score, 0.0) AS comment_score,
        COALESCE(d.comment_count, 0) AS comment_count
    FROM prices p
    LEFT JOIN daily_sentiment d
        ON d.symbol = p.symbol
        AND d.trading_date = p.date
        AND d.model = 'BERTurk'
    WHERE p.symbol = ?
    ORDER BY p.date;
    """
    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute("PRAGMA foreign_keys = ON;")
        df = pd.read_sql(query, conn, params=(symbol,), parse_dates=["date"])

    if df.empty:
        raise ValueError(f"{symbol} hissesi için veritabanında kayıt bulunamadı.")

    return df


def compute_rsi(series: pd.Series, window: int = 14) -> pd.Series:
    """Göreceli Güç Endeksi (RSI) hesaplar."""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.rolling(window=window, min_periods=window).mean()
    avg_loss = loss.rolling(window=window, min_periods=window).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50.0)


def build_features(symbol: str, db_path: Path = DB_PATH) -> pd.DataFrame:
    """Model eğitimi için özellik setini ve t+1 hedef yönünü oluşturur."""
    df = load_raw_data(symbol, db_path)

    # Teknik göstergeler (İG-16)
    df["daily_return"] = df["adj_close"].pct_change()
    df["ma_20"] = df["adj_close"].rolling(window=20).mean()
    df["ma_50"] = df["adj_close"].rolling(window=50).mean()
    df["volatility_20"] = df["daily_return"].rolling(window=20).std()
    df["rsi_14"] = compute_rsi(df["adj_close"], window=14)

    # Duygu gürültüsünü azaltmak için 5 günlük hareketli ortalama
    df["news_score_ma5"] = df["news_score"].rolling(window=5).mean()
    df["comment_score_ma5"] = df["comment_score"].rolling(window=5).mean()

    # Hedef değişken: Bir sonraki işlem gününün yönü (t+1 > t ise 1, değilse 0)
    df["next_close"] = df["adj_close"].shift(-1)
    df["target"] = (df["next_close"] > df["adj_close"]).astype("Int64")

    # İlk 50 gün (MA-50 nedeniyle NaN) ve son gün (t+1 henüz yok) temizlenir
    df = df.dropna(subset=["ma_50", "volatility_20", "next_close"]).copy()
    df["target"] = df["target"].astype(int)
    df = df.drop(columns=["next_close"])

    return df.reset_index(drop=True)


if __name__ == "__main__":
    sample_df = build_features("THYAO")
    print(f"THYAO özellik seti hazır: {len(sample_df)} satır")
    print(f"Tarih aralığı: {sample_df['date'].min().date()} -> {sample_df['date'].max().date()}")
    print("Hedef dağılımı (1=Yükseliş, 0=Düşüş/Sabit):")
    print(sample_df["target"].value_counts(normalize=True).round(3))
    print("\nİlk 3 satır:")
    print(sample_df[["date", "daily_return", "rsi_14", "news_score", "target"]].head(3))
