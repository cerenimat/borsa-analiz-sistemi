"""
Veri toplama modülünün ortak ayarları.

Yeni bir hisse eklemek için yalnızca STOCKS sözlüğüne satır eklenir
(GAB İOG-D-03). Dosya yolları da tek yerden yönetilir.
"""

from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo

# ---- Hisseler ve dönem -------------------------------------------------
# Sembol THYAO biçiminde; ".IS" eki yalnızca yfinance'e istek atarken eklenir.
STOCKS = {
    "THYAO": "Türk Hava Yolları",
}
START_DATE = "2023-01-01"   # Ekip kararı: tüm kaynaklar bu tarihten başlar
YAHOO_SUFFIX = ".IS"

# ---- Seans saati ------------------------------------------------------
# BIST 18:10'da kapanır; Yahoo'nun veriyi güncellemesi için pay bırakıyoruz.
# Bu saatten önce bugünün satırı yarım gün sayılır ve kaydedilmez.
TIMEZONE = ZoneInfo("Europe/Istanbul")
DAY_COMPLETE_AFTER = time(18, 30)
# ---- Dosya yolları ----------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
DB_PATH = DATA_DIR / "borsa.db"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def yahoo_symbol(symbol: str) -> str:
    """THYAO -> THYAO.IS (yfinance'in beklediği biçim)."""
    return f"{symbol}{YAHOO_SUFFIX}"


def raw_csv_path(symbol: str) -> Path:
    """Bir hissenin ham CSV dosyasının yolu: data/raw/THYAO_raw.csv"""
    return RAW_DIR / f"{symbol}_raw.csv"


def clean_csv_path(symbol: str) -> Path:
    """Temiz CSV dosyasının yolu: data/processed/THYAO_clean.csv"""
    return PROCESSED_DIR / f"{symbol}_clean.csv"
