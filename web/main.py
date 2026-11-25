
import sqlite3
from forecasting.predict import predict_next_day
from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException

app = FastAPI(title="Borsa Analiz Sistemi")

# Proje ana klasorunu buluyoruz.
PROJE_KLASORU = Path(__file__).resolve().parent.parent

# Veritabaninin konumunu belirliyoruz.
VERITABANI = PROJE_KLASORU / "data" / "borsa.db"


@app.get("/")
def ana_sayfa():
    return {"mesaj": "Borsa Analiz Sistemi API calisiyor"}


@app.get("/fiyat/{sembol}")
def hisse_fiyatlari(
    sembol: str,
    start: date | None = None,
    end: date | None = None
):
    if start and end and start > end:
        raise HTTPException(
            status_code=400,
            detail="Baslangic tarihi bitis tarihinden sonra olamaz."
        )
    
    # Veritabanini salt okunur modda aciyoruz.
    with sqlite3.connect(
        f"{VERITABANI.as_uri()}?mode=ro",
        uri=True
    ) as db:
        db.row_factory = sqlite3.Row


        veriler = db.execute(
            """
            SELECT date, close, volume
            FROM prices
            WHERE symbol = ?
              AND (? IS NULL OR date >= ?)
              AND (? IS NULL OR date <= ?)
            ORDER BY date ASC
            """,
        (
            sembol.upper(),
            start.isoformat() if start else None,
            start.isoformat() if start else None,
            end.isoformat() if end else None,
            end.isoformat() if end else None
        )
        ).fetchall()


    if not veriler:
        raise HTTPException(
            status_code=404,
            detail="Bu hisse icin fiyat verisi bulunamadi."
        )

    return {
        "sembol": sembol.upper(),
        "fiyatlar": [dict(satir) for satir in veriler]
    }


@app.get("/hisseler")
def hisseleri_listele():
    with sqlite3.connect(
        f"{VERITABANI.as_uri()}?mode=ro",
        uri=True
    ) as db:
        db.row_factory = sqlite3.Row

        hisseler = db.execute(
            """
            SELECT symbol, name
            FROM stocks
            ORDER BY symbol ASC
            """
        ).fetchall()

    return {
        "hisseler": [dict(hisse) for hisse in hisseler]
    }

@app.get("/tahmin/{sembol}")
def hisse_tahmini(sembol: str):
    try:
        sonuc = predict_next_day(sembol.upper())
        return sonuc

    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"{sembol.upper()} için eğitilmiş model bulunamadı."
        )


@app.get("/duygu/{sembol}")
def duygu_analizi(
    sembol: str,
    baslangic: date | None = None,
    bitis: date | None = None
):
    if baslangic and bitis and baslangic > bitis:
        raise HTTPException(
            status_code=400,
            detail="Başlangıç tarihi bitiş tarihinden büyük olamaz."
        )

    sorgu = """
        SELECT trading_date, news_avg_score, news_count,
               comment_avg_score, comment_count
        FROM daily_sentiment
        WHERE symbol = ? AND model = ?
    """

    parametreler = [sembol.upper(), "BERTurk"]

    if baslangic:
        sorgu += " AND trading_date >= ?"
        parametreler.append(baslangic.isoformat())

    if bitis:
        sorgu += " AND trading_date <= ?"
        parametreler.append(bitis.isoformat())

    sorgu += " ORDER BY trading_date ASC"

    with sqlite3.connect(
        f"file:{VERITABANI.as_posix()}?mode=ro",
        uri=True
    ) as conn:
        conn.row_factory = sqlite3.Row
        sonuclar = conn.execute(sorgu, parametreler).fetchall()

    return {
        "sembol": sembol.upper(),
        "model": "BERTurk",
        "duygu_analizleri": [dict(satir) for satir in sonuclar]
    }

@app.get("/icerikler/{sembol}")
def icerikleri_getir(
    sembol: str,
    baslangic: date | None = None,
    bitis: date | None = None
):
    if baslangic and bitis and baslangic > bitis:
        raise HTTPException(
            status_code=400,
            detail="Başlangıç tarihi bitiş tarihinden büyük olamaz."
        )

    sorgu = """
        SELECT c.id, c.published_at, c.type, c.source,
               c.title, c.text, c.url, c.trading_date,
               s.label, s.score
        FROM contents c
        JOIN content_symbols cs ON cs.content_id = c.id
        JOIN sentiments s ON s.content_id = c.id
        WHERE cs.symbol = ?
          AND s.model = ?
          AND c.purpose = 'analysis'
    """

    parametreler = [sembol.upper(), "BERTurk"]

    if baslangic:
        sorgu += " AND c.trading_date >= ?"
        parametreler.append(baslangic.isoformat())

    if bitis:
        sorgu += " AND c.trading_date <= ?"
        parametreler.append(bitis.isoformat())

    sorgu += " ORDER BY c.published_at DESC LIMIT 50"

    with sqlite3.connect(
        f"file:{VERITABANI.as_posix()}?mode=ro",
        uri=True
    ) as conn:
        conn.row_factory = sqlite3.Row
        sonuclar = conn.execute(
            sorgu, parametreler
        ).fetchall()

    return {
        "sembol": sembol.upper(),
        "model": "BERTurk",
        "icerikler": [dict(satir) for satir in sonuclar]
    }


