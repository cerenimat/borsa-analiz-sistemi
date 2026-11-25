
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


