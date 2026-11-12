"""
News headline collector (Google News RSS)

For each stock in the `stocks` table (BIST 50) queries the Google News RSS
search month by month from 2023-01 to today with

    ("<company name>" OR <alias> ... OR <CODE>) hisse after:<month> before:<next month>

keeps the items whose headline mentions the company (name, alias or code), and
writes them to the shared database (data/borsa.db):

    contents         one row per headline (type = 'news', source = publisher)
    content_symbols  one row per (headline, stock)
    update_log       one row per stock and run (source = 'news')

Afterwards assign_trading_dates() fills empty trading_date fields.

Per requirement İOG-Y-03 (requirements document) only the headline, source,
date and link are stored; article texts are not downloaded. `text` is the
headline, which is what the sentiment models score.

Run (from the project root):
    python sentiment/fetch_news.py                    # all stocks
    python sentiment/fetch_news.py THYAO PGSUS        # only these stocks
    python sentiment/fetch_news.py --retry-failed     # stocks without a successful run
    python sentiment/fetch_news.py --db data/test.db  # another database file
    python sentiment/fetch_news.py --db data/work.db --update   # only since each stock's last run
"""
import argparse
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from contextlib import closing
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "data_collection"))

from config import DB_PATH, TIMEZONE  # noqa: E402
from database import (assign_trading_dates, connect, create_schema,  # noqa: E402
                      seed_stocks)
from incremental import start_dates  # noqa: E402

START_MONTH = date(2023, 1, 1)        # team decision: all sources start on 2023-01-01
WAIT_SECONDS = 1.5                    # pause between requests (Google limits fast clients)
BLOCK_WAITS = (60, 180, 600)          # seconds to wait when Google answers 429/503
API = "https://news.google.com/rss/search"
HEADERS = {"User-Agent": "Mozilla/5.0"}

# Other names a company is reported under. Old codes matter: TRALT and TRMET traded
# as KOZAL and KOZAA until November 2025, so older headlines use those names.
ALIASES = {
    "THYAO": ["THY"],
    "EREGL": ["Erdemir"],
    "SASA": ["Sasa"],
    "TRALT": ["Koza Altın", "KOZAL"],
    "TRMET": ["Koza Anadolu", "KOZAA"],
    "GUBRF": ["Gübre Fabrikaları"],
    "PETKM": ["Petkim"],
    "TUPRS": ["Tüpraş"],
    "KRDMD": ["Kardemir"],
    "SISE": ["Şişecam"],
    "TOASO": ["Tofaş"],
    "ISCTR": ["İşbank"],
    "GARAN": ["Garanti Bankası"],   # plain "garanti" is an ordinary word (guarantee)
}

INSERT_CONTENT = """
INSERT INTO contents (type, source, title, text, url, published_at,
                      purpose, source_id, category, is_company_notice)
VALUES ('news', ?, ?, ?, ?, ?, 'analysis', ?, NULL, NULL)
ON CONFLICT (source, source_id) DO NOTHING
"""
FIND_CONTENT = "SELECT id FROM contents WHERE source = ? AND source_id = ?"
INSERT_LINK = "INSERT OR IGNORE INTO content_symbols (content_id, symbol) VALUES (?, ?)"
INSERT_LOG = """
INSERT INTO update_log (source, symbol, run_at, status, input_rows, removed,
                        inserted, existing, detail)
VALUES ('news', ?, ?, ?, ?, ?, ?, ?, ?)
"""


class Blocked(Exception):
    """Google keeps refusing requests; continue later with --retry-failed."""


def tr_lower(text):
    """Turkish-aware lower case (İ -> i, I -> ı) so that names match in any case."""
    return text.replace("İ", "i").replace("I", "ı").lower()


def search_terms(symbol, name):
    """Company name, aliases and the stock code (duplicates removed, order kept)."""
    terms = [name] if name else []
    terms += ALIASES.get(symbol, []) + [symbol]
    return list(dict.fromkeys(terms))


def build_query(terms, start, end):
    names = " OR ".join(f'"{t}"' if " " in t else t for t in terms)
    return f"({names}) hisse after:{start.isoformat()} before:{end.isoformat()}"


def months(first=START_MONTH):
    """(first day, first day of next month) from the month of `first` to the current month."""
    today = date.today()
    start = first.replace(day=1)
    while start <= today:
        end = date(start.year + start.month // 12, start.month % 12 + 1, 1)
        yield start, end
        start = end


def fetch_rss(query):
    """Returns the <item> elements of one Google News RSS search."""
    blocked = 0
    for attempt in range(1, 4 + len(BLOCK_WAITS)):
        try:
            r = requests.get(API, params={"q": query, "hl": "tr", "gl": "TR", "ceid": "TR:tr"},
                             headers=HEADERS, timeout=30)
        except requests.RequestException:
            if attempt >= 3:
                raise
            time.sleep(5 * attempt)
            continue
        if r.status_code in (429, 503):
            if blocked >= len(BLOCK_WAITS):
                raise Blocked(f"HTTP {r.status_code}")
            print(f"  Google: HTTP {r.status_code}; waiting {BLOCK_WAITS[blocked]} s ...")
            time.sleep(BLOCK_WAITS[blocked])
            blocked += 1
            continue
        r.raise_for_status()
        time.sleep(WAIT_SECONDS)
        return ET.fromstring(r.content).findall(".//item")
    raise Blocked("too many attempts")


def to_content(item):
    """Converts one RSS item to the values of INSERT_CONTENT."""
    source = (item.findtext("source") or "").strip() or "Google News"
    title = (item.findtext("title") or "").strip()
    suffix = f" - {source}"
    if title.endswith(suffix):                       # Google appends " - <publisher>"
        title = title[: -len(suffix)].strip()
    if not title:
        raise ValueError("empty title")
    published = parsedate_to_datetime(item.findtext("pubDate"))
    published = published.astimezone(TIMEZONE).isoformat(timespec="seconds")
    source_id = (item.findtext("guid") or item.findtext("link") or "").strip()
    if not source_id:
        raise ValueError("no guid")
    return (source, title, title, item.findtext("link"), published, source_id)


def mentions(title, terms):
    """True if the headline names the company (whole word, any case)."""
    low = tr_lower(title)
    return any(re.search(rf"(?<!\w){re.escape(tr_lower(t))}(?!\w)", low) for t in terms)


def save_items(conn, symbol, terms, items):
    """Writes one month's headlines in one transaction; returns (inserted, existing, off_topic, skipped)."""
    inserted = existing = off_topic = skipped = 0
    with conn:
        for item in items:
            try:
                row = to_content(item)
            except Exception:
                skipped += 1
                continue
            if not mentions(row[1], terms):
                off_topic += 1                       # query matched, headline is about something else
                continue
            cur = conn.execute(INSERT_CONTENT, row)
            if cur.rowcount:
                inserted += 1
            else:
                existing += 1
            # The same headline can be found for several stocks; the link is written in any case.
            content_id = conn.execute(FIND_CONTENT, (row[0], row[5])).fetchone()[0]
            conn.execute(INSERT_LINK, (content_id, symbol))
    return inserted, existing, off_topic, skipped


def write_log(conn, symbol, status, received, removed, inserted, existing, detail):
    run_at = datetime.now(TIMEZONE).isoformat(timespec="seconds")
    with conn:
        conn.execute(INSERT_LOG, (symbol, run_at, status, received, removed,
                                  inserted, existing, json.dumps(detail, ensure_ascii=False)))


def latest_runs(conn):
    """{symbol: (status, detail)} of each stock's latest 'news' run."""
    rows = conn.execute(
        "SELECT symbol, status, detail FROM update_log u WHERE source = 'news' AND id = "
        "(SELECT MAX(id) FROM update_log WHERE source = 'news' AND symbol = u.symbol)"
    ).fetchall()
    return {s: (status, json.loads(detail or "{}")) for s, status, detail in rows}


def main(symbols=None, db_path=DB_PATH, retry_failed=False, update=False, since=None):
    with closing(connect(db_path)) as conn:
        create_schema(conn)
        seed_stocks(conn)   # content_symbols needs the stocks table
        stocks = conn.execute("SELECT symbol, name FROM stocks ORDER BY symbol").fetchall()
        if symbols:
            unknown = set(symbols) - {s for s, _ in stocks}
            if unknown:
                sys.exit(f"Unknown symbols: {', '.join(sorted(unknown))}")
            stocks = [(s, n) for s, n in stocks if s in symbols]
        runs = latest_runs(conn) if retry_failed else {}
        if retry_failed:
            stocks = [(s, n) for s, n in stocks if runs.get(s, ("", {}))[0] != "success"]
            print(f"{len(stocks)} stocks without a successful run\n")
        firsts = start_dates(conn, "news", since) if update else {}
        if update:
            prev_runs = latest_runs(conn)
            print(f"Update: from {min(firsts.values(), default=START_MONTH)} "
                  f"(each stock {'from ' + str(since) if since else 'from its last run minus a margin'})\n")

        totals = {"inserted": 0, "existing": 0, "off_topic": 0}
        blocked = False
        for symbol, name in stocks:
            terms = search_terms(symbol, name)
            # With --retry-failed, months finished in the previous (interrupted) run are skipped.
            completed = list(runs.get(symbol, ("", {}))[1].get("completed_months", []))
            if update:   # months are searched again from the start date; earlier ones stay completed
                first = firsts.get(symbol, START_MONTH)
                done = prev_runs.get(symbol, ("", {}))[1].get("completed_months", [])
                completed = [m for m in done if m < first.isoformat()[:7]]
            received = inserted = existing = off_topic = skipped = 0
            per_year, errors = {}, []
            month = None
            try:
                for start, end in months(firsts.get(symbol, START_MONTH) if update else START_MONTH):
                    month = start.isoformat()[:7]
                    if month in completed:
                        continue
                    items = fetch_rss(build_query(terms, start, end))
                    received += len(items)
                    i, x, o, s = save_items(conn, symbol, terms, items)
                    inserted, existing, off_topic, skipped = (inserted + i, existing + x,
                                                              off_topic + o, skipped + s)
                    per_year[start.year] = per_year.get(start.year, 0) + i + x
                    if len(items) >= 100:            # Google returns at most 100 items per query
                        errors.append(f"{month}: 100 items (limit), some may be missing")
                    if end <= date.today():          # the running month is never marked complete
                        completed.append(month)
            except Blocked as e:
                blocked = True
                errors.append(f"{month}: blocked by Google ({e})")
            except Exception as e:
                errors.append(f"{month}: {type(e).__name__}: {e}")

            hard_errors = [e for e in errors if "limit" not in e]
            status = "error" if hard_errors else "success"
            detail = {"query_terms": terms, "completed_months": sorted(set(completed)),
                      "kept_per_year": per_year, "off_topic": off_topic, "errors": errors[:20]}
            write_log(conn, symbol, status, received, off_topic + skipped, inserted, existing, detail)
            totals["inserted"] += inserted
            totals["existing"] += existing
            totals["off_topic"] += off_topic
            years_text = " ".join(f"{y}:{n}" for y, n in per_year.items())
            print(f"{symbol:<6} received: {received:>5} | kept: {inserted + existing:>5} ({years_text}) | "
                  f"new: {inserted:>5} | off-topic: {off_topic:>4} | {status}")
            if blocked:
                print("\nGoogle is refusing requests. Wait an hour, then run again with --retry-failed.")
                break

        assigned, missing = assign_trading_dates(conn)

    print(f"\nNew headlines: {totals['inserted']} | already in database: {totals['existing']} | "
          f"off-topic (not saved): {totals['off_topic']}")
    print(f"Trading date assigned: {assigned} | still empty (no price data yet): {missing}")
    print(f"Database: {db_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Collect news headlines for BIST 50 stocks.")
    parser.add_argument("symbols", nargs="*", help="only these stocks (default: all)")
    parser.add_argument("--retry-failed", action="store_true",
                        help="only stocks without a successful run")
    parser.add_argument("--db", type=Path, default=DB_PATH, help="database file")
    parser.add_argument("--update", action="store_true",
                        help="only since each stock's last successful run (minus a few days)")
    parser.add_argument("--since", type=date.fromisoformat, help="with --update: start date for every stock")
    args = parser.parse_args()
    main([s.upper() for s in args.symbols] or None, db_path=args.db, retry_failed=args.retry_failed,
         update=args.update or bool(args.since), since=args.since)
