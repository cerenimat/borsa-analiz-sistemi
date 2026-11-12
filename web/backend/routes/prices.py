
from fastapi import APIRouter, HTTPException, Query
from datetime import date
from web.backend.database import get_db_connection

router = APIRouter()


@router.get("/prices/{symbol}")
def get_prices(
    symbol: str,
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to")
):
    symbol = symbol.upper()

    if from_date and to_date and from_date > to_date:
        raise HTTPException(
            status_code=400,
            detail="Başlangıç tarihi bitiş tarihinden sonra olamaz."
        )

    connection = get_db_connection()

    try:
        query = """
            SELECT symbol, date, open, high, low, close, adj_close, volume
            FROM prices
            WHERE symbol = ?
        """

        params = [symbol]

        if from_date:
            query += " AND date >= ?"
            params.append(from_date.isoformat())

        if to_date:
            query += " AND date <= ?"
            params.append(to_date.isoformat())

        query += " ORDER BY date ASC"

        prices = connection.execute(query, params).fetchall()

        if not prices:
            raise HTTPException(
                status_code=404,
                detail=f"{symbol} için fiyat verisi bulunamadı."
            )

        return [dict(price) for price in prices]

    finally:
        connection.close()
