"""
KAP disclosure collector

Fetches KAP disclosures for the stocks in the `stocks` table (BIST 50) from
START_DATE to today through KAP's own query API, one quarter at a time
(KAP allows at most a 3-month range per query), and writes them to the
shared database (data/borsa.db):

    contents         one row per disclosure (unique on source, source_id)
    content_symbols  one row per (disclosure, stock) it was published under
    update_log       one row per stock and run (source = 'kap')

Afterwards assign_trading_dates() fills empty trading_date fields.

Per requirement İOG-Y-03 (requirements document), only title, short summary,
date, source and link are stored. Re-running is safe: existing disclosures are
not inserted again, but missing stock links are still added.

Run (from the project root):
    python sentiment/fetch_kap.py                # all stocks
    python sentiment/fetch_kap.py THYAO PGSUS    # only these stocks
    python sentiment/fetch_kap.py --retry-failed # only the queries that failed last time
"""
import json
import sys
import time
from contextlib import closing
from datetime import date, datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "data_collection"))

from config import DB_PATH, TIMEZONE  # noqa: E402
from database import (assign_trading_dates, connect, create_schema,  # noqa: E402
                      seed_stocks)

START_DATE = date(2023, 1, 1)   # team decision: all sources start here
WAIT_SECONDS = 1.5              # pause between requests to avoid loading KAP
MAX_RETRIES = 3                 # a failed request (other than 429) is tried at most this many times
RATE_LIMIT_WAITS = (60, 120, 240, 480)   # seconds to wait after each "429 Request Limit Exceeded"

API = "https://www.kap.org.tr/tr/api/disclosure/members/byCriteria"
DISCLOSURE_URL = "https://www.kap.org.tr/tr/Bildirim/{}"
HEADERS = {
    "Content-Type": "application/json",
    "Accept-Language": "tr",
    "User-Agent": "Mozilla/5.0",
    "Origin": "https://www.kap.org.tr",
    "Referer": "https://www.kap.org.tr/tr/bildirim-sorgu",
}
# Bulk announcements from these institutions (e.g. SPK trading bans) are not the company's own notices.
# Values are matched against KAP data, so they stay in Turkish.
MARKET_INSTITUTIONS = ("BORSA İSTANBUL", "MERKEZİ KAYIT", "İSTANBUL TAKAS")

INSERT_CONTENT = """
INSERT INTO contents (type, source, title, text, url, published_at,
                      purpose, source_id, category, is_company_notice)
VALUES ('kap', ?, ?, ?, ?, ?, 'analysis', ?, ?, ?)
ON CONFLICT (source, source_id) DO NOTHING
"""
FIND_CONTENT = "SELECT id FROM contents WHERE source = ? AND source_id = ?"
INSERT_LINK = "INSERT OR IGNORE INTO content_symbols (content_id, symbol) VALUES (?, ?)"
INSERT_LOG = """
INSERT INTO update_log (source, symbol, run_at, status, input_rows, removed,
                        inserted, existing, detail)
VALUES ('kap', ?, ?, ?, ?, ?, ?, ?, ?)
"""


def build_query(oid, start, end):
    return {
        "fromDate": start, "toDate": end, "memberType": "IGS",
        "mkkMemberOidList": [oid], "inactiveMkkMemberOidList": [],
        "disclosureClass": "", "subjectList": [], "isLate": "",
        "mainSector": "", "sector": "", "subSector": "", "marketOid": "", "index": "",
        "bdkReview": "", "bdkMemberOidList": [], "year": "", "term": "", "ruleType": "",
        "period": "", "fromSrc": False, "srcCategory": "", "disclosureIndexList": [],
    }


def quarters():
    """Yields 3-month (start, end) ranges from START_DATE to today."""
    today = date.today()
    start = START_DATE
    while start <= today:
        month = start.month + 3
        next_start = date(start.year + (month - 1) // 12, (month - 1) % 12 + 1, 1)
        end = min(date.fromordinal(next_start.toordinal() - 1), today)
        yield start.isoformat(), end.isoformat()
        start = next_start


def query_kap(oid, start, end):
    """Sends a request to KAP.

    429 (request limit exceeded): waits RATE_LIMIT_WAITS (or KAP's Retry-After) and tries again.
    Other errors: retries up to MAX_RETRIES times with short increasing waits.
    """
    errors = rate_limited = 0
    while True:
        try:
            r = requests.post(API, headers=HEADERS, json=build_query(oid, start, end), timeout=60)
            if r.status_code == 429 and rate_limited < len(RATE_LIMIT_WAITS):
                retry_after = r.headers.get("Retry-After", "")
                wait = int(retry_after) if retry_after.isdigit() else RATE_LIMIT_WAITS[rate_limited]
                rate_limited += 1
                print(f"  KAP request limit reached; waiting {wait} s ...")
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r.json()
        except Exception:
            errors += 1
            if errors >= MAX_RETRIES:
                raise
            time.sleep(WAIT_SECONDS * 5 * errors)


def failed_quarters(conn):
    """Returns {symbol: [(start, end), ...]} from each stock's latest 'kap' run that ended with errors."""
    rows = conn.execute(
        "SELECT symbol, status, detail FROM update_log u WHERE source = 'kap' AND id = "
        "(SELECT MAX(id) FROM update_log WHERE source = 'kap' AND symbol = u.symbol)"
    ).fetchall()
    result = {}
    for symbol, status, detail in rows:
        if status == "error":
            failed = json.loads(detail or "{}").get("failed_queries", [])
            result[symbol] = [(f["start_date"], f["end_date"]) for f in failed]
    return result


def to_content(record):
    """Converts one KAP record to the values of INSERT_CONTENT."""
    published = datetime.strptime(record["publishDate"], "%d.%m.%Y %H:%M:%S")
    published = published.replace(tzinfo=TIMEZONE).isoformat(timespec="seconds")
    source = (record.get("kapTitle") or "").strip() or "KAP"   # institution that published it
    source_id = str(record["disclosureIndex"])
    title = record.get("subject") or ""
    text = record.get("summary") or title                      # some notices have no summary
    is_company_notice = 0 if any(i in source.upper() for i in MARKET_INSTITUTIONS) else 1
    return (source, title, text, DISCLOSURE_URL.format(source_id), published,
            source_id, record.get("disclosureClass") or "", is_company_notice)


def save_records(conn, symbol, records):
    """Writes one stock's records in one transaction; returns (inserted, existing, skipped, errors)."""
    inserted = existing = 0
    errors = []
    with conn:
        for rec in records:
            try:
                row = to_content(rec)
            except Exception as e:
                # one malformed record should not drop the others
                errors.append(f"{rec.get('disclosureIndex')}: {type(e).__name__}: {e}")
                continue
            cur = conn.execute(INSERT_CONTENT, row)
            if cur.rowcount:
                inserted += 1
            else:
                existing += 1
            # The disclosure may already exist from another stock's query (joint notices,
            # bulk BIST announcements); the link for this stock is written in any case.
            content_id = conn.execute(FIND_CONTENT, (row[0], row[5])).fetchone()[0]
            conn.execute(INSERT_LINK, (content_id, symbol))
    return inserted, existing, len(errors), errors


def write_log(conn, symbol, status, received, skipped, inserted, existing, detail):
    run_at = datetime.now(TIMEZONE).isoformat(timespec="seconds")
    with conn:
        conn.execute(INSERT_LOG, (symbol, run_at, status, received, skipped,
                                  inserted, existing, json.dumps(detail, ensure_ascii=False)))


def main(symbols=None, db_path=DB_PATH, retry_failed=False):
    with closing(connect(db_path)) as conn:
        create_schema(conn)
        seed_stocks(conn)   # content_symbols needs the stocks table
        stocks = conn.execute(
            "SELECT symbol, kap_oid FROM stocks WHERE kap_oid IS NOT NULL ORDER BY symbol"
        ).fetchall()
        if symbols:
            unknown = set(symbols) - {s for s, _ in stocks}
            if unknown:
                sys.exit(f"Unknown symbols: {', '.join(sorted(unknown))}")
            stocks = [(s, o) for s, o in stocks if s in symbols]
        todo = failed_quarters(conn) if retry_failed else None
        if retry_failed:
            stocks = [(s, o) for s, o in stocks if s in todo]
            print(f"Retrying {sum(len(q) for q in todo.values())} failed queries "
                  f"for {len(stocks)} stocks\n")

        totals = {"inserted": 0, "existing": 0, "skipped": 0, "failed_queries": 0}
        for symbol, oid in stocks:
            received = inserted = existing = skipped = 0
            failed, record_errors = [], []
            for start, end in (todo[symbol] if retry_failed else quarters()):
                try:
                    records = query_kap(oid, start, end)
                except Exception as e:
                    error = f"{type(e).__name__}: {e}"
                    print(f"{symbol} {start}: ERROR {error}")
                    failed.append({"start_date": start, "end_date": end, "error": error})
                else:
                    received += len(records)
                    i, x, s, errs = save_records(conn, symbol, records)
                    inserted, existing, skipped = inserted + i, existing + x, skipped + s
                    record_errors += errs
                time.sleep(WAIT_SECONDS)

            status = "error" if failed else "success"
            detail = {"failed_queries": failed, "skipped_records": record_errors[:20]}
            write_log(conn, symbol, status, received, skipped, inserted, existing, detail)
            totals["inserted"] += inserted
            totals["existing"] += existing
            totals["skipped"] += skipped
            totals["failed_queries"] += len(failed)
            print(f"{symbol:<6} received: {received:>5} | new: {inserted:>5} | "
                  f"existing: {existing:>5} | skipped: {skipped} | failed queries: {len(failed)}")

        assigned, missing = assign_trading_dates(conn)

    print(f"\nNew disclosures: {totals['inserted']} | already in database: {totals['existing']} | "
          f"skipped records: {totals['skipped']} | failed queries: {totals['failed_queries']}")
    print(f"Trading date assigned: {assigned} | still empty (no price data yet): {missing}")
    if totals["failed_queries"]:
        print("Failed queries are listed in update_log (status = 'error'); "
              "run again with --retry-failed to fill them.")
    print(f"Database: {db_path}")


if __name__ == "__main__":
    args = sys.argv[1:]
    retry = "--retry-failed" in args
    main([a.upper() for a in args if not a.startswith("--")] or None, retry_failed=retry)
