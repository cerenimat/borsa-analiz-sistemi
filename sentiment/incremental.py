"""
Start dates for incremental updates (--update) of the collectors

A collector run with --update does not go back to 2023: each stock starts from
the date of its own last successful run of that source, minus MARGIN_DAYS, so
that items published late (or indexed late by the source) are not missed.
Items that are already in the database are not inserted again, so the overlap
costs a few requests but no duplicates.

A stock without a successful run in the database falls back to the full
period (START_DATE): it was never collected, so there is nothing to update.
"""
from datetime import date, timedelta

START_DATE = date(2023, 1, 1)   # team decision: all sources start here
MARGIN_DAYS = 7


def last_successes(conn, source):
    """{symbol: date of the latest successful run} for one update_log source."""
    rows = conn.execute(
        "SELECT symbol, MAX(run_at) FROM update_log WHERE source = ? AND status = 'success' GROUP BY symbol",
        (source,)).fetchall()
    return {symbol: date.fromisoformat(run_at[:10]) for symbol, run_at in rows if symbol}


def start_dates(conn, source, since=None, margin=MARGIN_DAYS):
    """{symbol: first date to collect} for an --update run. An explicit `since` (date)
    applies to every stock; otherwise each stock starts `margin` days before its last
    successful run. Stocks missing from the result start at START_DATE."""
    if since:
        return {s: since for (s,) in conn.execute("SELECT symbol FROM stocks")}
    return {s: max(START_DATE, d - timedelta(days=margin)) for s, d in last_successes(conn, source).items()}
