
from fastapi import APIRouter
from web.backend.database import get_db_connection

router = APIRouter()


@router.get("/stocks")
def get_stocks():
    connection = get_db_connection()

    try:
        stocks = connection.execute("""
            SELECT symbol, name, yahoo_symbol, exchange, currency
            FROM stocks
            ORDER BY symbol
        """).fetchall()

        return [dict(stock) for stock in stocks]

    finally:
        connection.close()
