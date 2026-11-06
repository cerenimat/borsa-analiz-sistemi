"""
Veri toplama modülünün ortak ayarları.

Hisse listesinin tek kaynağı config/bist50_oid.json dosyasıdır (Ceren'in
KAP betiği de aynı dosyayı okur). Yeni bir hisse eklemek için yalnızca bu
dosyaya satır eklenir (GAB İOG-D-03). Dosya yolları da tek yerden yönetilir.
"""

import json
from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo

# ---- Dosya yolları ----------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
STOCKS_FILE = PROJECT_ROOT / "config" / "bist50_oid.json"
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
DB_PATH = DATA_DIR / "borsa.db"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"

# ---- Dönem ------------------------------------------------------------
START_DATE = "2023-01-01"   # Ekip kararı: tüm kaynaklar bu tarihten başlar
YAHOO_SUFFIX = ".IS"

# ---- Seans saati ------------------------------------------------------
# BIST 18:10'da kapanır; Yahoo'nun veriyi güncellemesi için pay bırakıyoruz.
# Bu saatten önce bugünün satırı yarım gün sayılır ve kaydedilmez.
TIMEZONE = ZoneInfo("Europe/Istanbul")
DAY_COMPLETE_AFTER = time(18, 30)
# Bu saatte ve sonrasında yayımlanan haber/yorum bir sonraki işlem gününe
# atanır (GAB İG-10). published_at değerleri İstanbul saatiyle (+03:00) olmalı.
CONTENT_CUTOFF = "18:10"


def load_stocks() -> list[dict]:
    """config/bist50_oid.json dosyasını okur ve kontrol eder.

    Her eleman: {"symbol": "THYAO", "name": "...", "kap_oid": "..."}
    """
    if not STOCKS_FILE.exists():
        raise FileNotFoundError(
            f"{STOCKS_FILE} bulunamadı. Hisse listesi bu dosyadan okunur.")
    stocks = json.loads(STOCKS_FILE.read_text(encoding="utf-8"))

    seen = set()
    for item in stocks:
        symbol = item.get("symbol", "")
        if not symbol or symbol != symbol.upper() or "." in symbol:
            raise ValueError(f"Geçersiz sembol: {symbol!r} (THYAO biçimi)")
        if symbol in seen:
            raise ValueError(f"Sembol iki kez geçiyor: {symbol}")
        if not item.get("kap_oid"):
            raise ValueError(f"{symbol} için kap_oid boş")
        seen.add(symbol)
    return stocks


# Sembol -> şirket adı (ör. {"THYAO": "Türk Hava Yolları", ...})
STOCKS = {item["symbol"]: item["name"] for item in load_stocks()}


def yahoo_symbol(symbol: str) -> str:
    """THYAO -> THYAO.IS (yfinance'in beklediği biçim)."""
    return f"{symbol}{YAHOO_SUFFIX}"


def raw_csv_path(symbol: str) -> Path:
    """Bir hissenin ham CSV dosyasının yolu: data/raw/THYAO_raw.csv"""
    return RAW_DIR / f"{symbol}_raw.csv"


def clean_csv_path(symbol: str) -> Path:
    """Temiz CSV dosyasının yolu: data/processed/THYAO_clean.csv"""
    return PROCESSED_DIR / f"{symbol}_clean.csv"
