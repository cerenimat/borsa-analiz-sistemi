
import sqlite3
from pathlib import Path

# Proje ana dizinini bul
BASE_DIR = Path(__file__).resolve().parents[2]

# Ortak veritabanı dosyasının yolu
DB_PATH = BASE_DIR / "data" / "borsa.db"


def get_db_connection():
    """
    SQLite veritabanına salt okunur bağlantı kurar.
    """

    if not DB_PATH.exists():
        raise FileNotFoundError(f"Veritabanı bulunamadı: {DB_PATH}")

    connection = sqlite3.connect(
        f"{DB_PATH.as_uri()}?mode=ro",
        uri=True
    )

    connection.row_factory = sqlite3.Row

    return connection
