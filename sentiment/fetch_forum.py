"""
Hisse.net forum collector

Hisse.net (vBulletin) has one discussion thread per stock in its market
sub-forums ("THYAO (Türk Hava Yolları) Forumu", "TCELL - Türkcell", ...).
For each stock in the `stocks` table this script finds its thread(s), skips
the pages older than START_DATE with a binary search, and stores every post
from START_DATE to today in the database (default data/hissenet.db):

    contents         one row per post (type = 'comment', source = 'Hisse.net')
    content_symbols  one row per (post, stock)
    update_log       one row per stock and run (source = 'forum')

Afterwards assign_trading_dates() fills empty trading_date fields.

What is stored: post text (quoted earlier posts removed), date, thread title
and a link to the post. No user name, title, signature or profile data
(requirement İOG-Y-04). robots.txt allows thread and forum pages; the
disallowed paths (profiles, search, print, ?s= session links ...) are never
requested. Requests are spaced WAIT_SECONDS apart.

Re-running is safe and incremental: each thread continues from the last page
read in the previous run of that stock, existing posts are not inserted again.

Run (from the project root):
    python sentiment/fetch_forum.py --db data/hissenet.db                 # all stocks
    python sentiment/fetch_forum.py --db data/hissenet.db THYAO PGSUS     # only these
    python sentiment/fetch_forum.py --db data/hissenet.db --retry-failed  # unfinished stocks
    python sentiment/fetch_forum.py --db data/forum_test.db THYAO --max-pages 3   # quick test
    python sentiment/fetch_forum.py --db data/forum_test.db --check                # list threads only
"""
import argparse
import json
import re
import sys
import time
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "data_collection"))

from config import DB_PATH, TIMEZONE  # noqa: E402
from database import (assign_trading_dates, connect, create_schema,  # noqa: E402
                      seed_stocks)

START_DATE = date(2023, 1, 1)         # team decision: all sources start here
WAIT_SECONDS = 2.0                    # pause between requests
BLOCK_WAITS = (60, 180, 600)          # seconds to wait when the site answers 403/429/503
SOURCE = "Hisse.net"
BASE = "https://www.hisse.net/topluluk/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept-Language": "tr-TR,tr;q=0.9",
}
# market sub-forums that hold the stock threads (found on forum.php)
SUBFORUM = re.compile(r'href="(forums/(\d+)-(?:yildiz-pazar|ana-pazar|alt-pazar)[^"?#]*)')
# old codes still used in thread titles (TRALT/TRMET were KOZAL/KOZAA until November 2025)
OLD_CODES = {"TRALT": ["KOZAL"], "TRMET": ["KOZAA"]}
# footer the mobile app appends to posts ("hisse.net kullanarak iPhone aracılığıyla gönderildi")
APP_FOOTER = re.compile(r"(hisse\.net kullanarak .{0,40}gönderildi|sent from .{0,40}using hisse\.net.*)$",
                        re.IGNORECASE)

INSERT_CONTENT = """
INSERT INTO contents (type, source, title, text, url, published_at,
                      purpose, source_id, category, is_company_notice)
VALUES ('comment', ?, ?, ?, ?, ?, 'analysis', ?, NULL, NULL)
ON CONFLICT (source, source_id) DO NOTHING
"""
FIND_CONTENT = "SELECT id FROM contents WHERE source = ? AND source_id = ?"
INSERT_LINK = "INSERT OR IGNORE INTO content_symbols (content_id, symbol) VALUES (?, ?)"
INSERT_LOG = """
INSERT INTO update_log (source, symbol, run_at, status, input_rows, removed,
                        inserted, existing, detail)
VALUES ('forum', ?, ?, ?, ?, ?, ?, ?, ?)
"""


class Blocked(Exception):
    """The site keeps refusing requests; continue later with --retry-failed."""


# ---------------------------------------------------------------- schema --

def ensure_forum_source(conn):
    """Schema v2 allows update_log.source only in ('yfinance','kap','news','youtube').
    SQLite cannot change a CHECK constraint, so the (small) update_log table is rebuilt
    with 'forum' added. Only the database given with --db is touched."""
    sql = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'update_log'").fetchone()[0]
    if "'forum'" in sql:
        return
    new_sql = sql.replace("'youtube')", "'youtube', 'forum')")
    if new_sql == sql:
        sys.exit("update_log CHECK has an unexpected form; ask Elisar to add 'forum' to the schema.")
    with conn:
        conn.execute("ALTER TABLE update_log RENAME TO update_log_old")
        conn.execute(new_sql)
        conn.execute("INSERT INTO update_log SELECT * FROM update_log_old")
        conn.execute("DROP TABLE update_log_old")
    print("update_log: 'forum' added to the allowed sources (this database only).\n")


# ------------------------------------------------------------------ http --

class Site:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.referer = None
        self.requests = 0

    def get(self, path):
        blocked = 0
        for attempt in range(1, 4 + len(BLOCK_WAITS)):
            time.sleep(WAIT_SECONDS)
            try:
                r = self.session.get(BASE + path, timeout=30,
                                     headers={"Referer": self.referer} if self.referer else {})
            except requests.RequestException:
                if attempt >= 3:
                    raise
                time.sleep(5 * attempt)
                continue
            self.requests += 1
            if r.status_code in (403, 429, 503):
                if blocked >= len(BLOCK_WAITS):
                    raise Blocked(f"HTTP {r.status_code} for {path}")
                print(f"  Hisse.net: HTTP {r.status_code}; waiting {BLOCK_WAITS[blocked]} s ...")
                time.sleep(BLOCK_WAITS[blocked])
                blocked += 1
                continue
            r.raise_for_status()
            self.referer = r.url
            # the site declares ISO-8859-9; cp1254 is its superset (curly quotes etc.)
            return BeautifulSoup(r.content.decode("cp1254", errors="replace"), "html.parser")
        raise Blocked(f"too many attempts for {path}")


def last_page(soup, base_path):
    """Highest /pageN number linked from a forum or thread page (1 if none)."""
    nums = [int(m.group(1)) for a in soup.find_all("a", href=True)
            if (m := re.fullmatch(re.escape(base_path) + r"/page(\d+)",
                                  a["href"].split("?")[0].removeprefix(BASE)))]
    return max(nums, default=1)


# --------------------------------------------------------- thread lookup --

def find_threads(site):
    """{thread path: title} for every thread in the market sub-forums."""
    home = site.get("forum.php")
    subforums = sorted({m.group(1) for m in SUBFORUM.finditer(str(home))})
    threads = {}
    for sub in subforums:
        first = site.get(sub)
        for page in range(1, last_page(first, sub) + 1):
            soup = first if page == 1 else site.get(f"{sub}/page{page}")
            for a in soup.select('a[id^="thread_title_"]'):
                threads[a["href"].split("?")[0].removeprefix(BASE)] = a.get_text(" ", strip=True)
    return threads


def threads_for(symbol, threads):
    codes = [symbol] + OLD_CODES.get(symbol, [])
    pattern = re.compile(rf"^\W*(?:{'|'.join(codes)})(?![A-Za-z0-9])", re.IGNORECASE)
    return {path: title for path, title in threads.items() if pattern.search(title)}


# ---------------------------------------------------------- post parsing --

def parse_date(text, now):
    """'04-11-2026, 16:55' / 'Bugün, 16:55' / 'Dün, 09:12' -> aware datetime (+03:00)."""
    text = text.replace("\xa0", " ").strip()
    day, _, clock = text.partition(",")
    hour, minute = (int(x) for x in clock.strip().split(":"))
    word = day.strip().lower()
    if word in ("bugün", "today"):
        d = now.date()
    elif word in ("dün", "yesterday"):
        d = now.date() - timedelta(days=1)
    else:
        d = datetime.strptime(day.strip(), "%d-%m-%Y").date()
    return datetime(d.year, d.month, d.day, hour, minute, tzinfo=TIMEZONE)


def parse_posts(soup, now):
    """[(post id, datetime, text)] of one thread page; quoted posts are removed."""
    posts = []
    for li in soup.select('li[id^="post_"]'):
        pid = li["id"].removeprefix("post_")
        date_el = li.select_one("span.date")
        body = li.select_one(f"#post_message_{pid} blockquote.postcontent")
        if not pid.isdigit() or date_el is None or body is None:
            continue
        for quote in body.select("div.bbcode_container"):
            quote.decompose()                        # earlier posts quoted in this one
        lines = [" ".join(line.split()) for line in body.get_text("\n").splitlines()]
        text = "\n".join(line for line in lines if line and not APP_FOOTER.search(line))
        posts.append((pid, parse_date(date_el.get_text(), now), text))
    return posts


def first_page_from(site, path, pages, start, now):
    """Smallest page whose newest post is on/after `start` (binary search, ~log2(pages) requests)."""
    lo, hi = 1, pages
    while lo < hi:
        mid = (lo + hi) // 2
        posts = parse_posts(site.get(f"{path}/page{mid}"), now)
        if posts and posts[-1][1].date() < start:
            lo = mid + 1
        else:
            hi = mid
    return lo


# ---------------------------------------------------------------- saving --

def save_posts(conn, symbol, title, posts, start):
    """Writes one page in one transaction; returns (inserted, existing, skipped_empty, before_start)."""
    inserted = existing = empty = old = 0
    with conn:
        for pid, when, text in posts:
            if when.date() < start:
                old += 1
                continue
            if not text:
                empty += 1                            # e.g. a post that only quoted another
                continue
            row = (SOURCE, title, text, f"{BASE}showthread.php?p={pid}",
                   when.isoformat(timespec="seconds"), pid)
            if conn.execute(INSERT_CONTENT, row).rowcount:
                inserted += 1
            else:
                existing += 1
            content_id = conn.execute(FIND_CONTENT, (SOURCE, pid)).fetchone()[0]
            conn.execute(INSERT_LINK, (content_id, symbol))
    return inserted, existing, empty, old


def write_log(conn, symbol, status, received, removed, inserted, existing, detail):
    run_at = datetime.now(TIMEZONE).isoformat(timespec="seconds")
    with conn:
        conn.execute(INSERT_LOG, (symbol, run_at, status, received, removed,
                                  inserted, existing, json.dumps(detail, ensure_ascii=False)))


def latest_runs(conn):
    rows = conn.execute(
        "SELECT symbol, status, detail FROM update_log u WHERE source = 'forum' AND id = "
        "(SELECT MAX(id) FROM update_log WHERE source = 'forum' AND symbol = u.symbol)"
    ).fetchall()
    return {s: (status, json.loads(detail or "{}")) for s, status, detail in rows}


# ------------------------------------------------------------------ main --

def main(symbols=None, db_path=DB_PATH, retry_failed=False, max_pages=None, check=False):
    with closing(connect(db_path)) as conn:
        create_schema(conn)
        seed_stocks(conn)
        ensure_forum_source(conn)
        stocks = [s for (s,) in conn.execute("SELECT symbol FROM stocks ORDER BY symbol")]
        if symbols:
            unknown = set(symbols) - set(stocks)
            if unknown:
                sys.exit(f"Unknown symbols: {', '.join(sorted(unknown))}")
            stocks = [s for s in stocks if s in symbols]
        runs = latest_runs(conn)
        if retry_failed:
            stocks = [s for s in stocks if runs.get(s, ("", {}))[0] != "success"]
            print(f"{len(stocks)} stocks without a successful run\n")
        if not stocks:
            return

        site = Site()
        print("Looking up the stock threads ...")
        all_threads = find_threads(site)
        print(f"{len(all_threads)} threads in the market sub-forums ({site.requests} requests)\n")
        if check:
            missing = []
            for symbol in stocks:
                mine = threads_for(symbol, all_threads)
                print(f"{symbol:<6} {len(mine)} | " + " ; ".join(mine.values()))
                if not mine:
                    missing.append(symbol)
            print(f"\nNo thread found for: {', '.join(missing) or '-'}")
            return

        totals = {"inserted": 0, "existing": 0}
        blocked = False
        for symbol in stocks:
            now = datetime.now(TIMEZONE)
            mine = threads_for(symbol, all_threads)
            prev = runs.get(symbol, ("", {}))[1].get("threads", {})
            detail = {"threads": {}, "errors": []}
            received = inserted = existing = removed = 0
            try:
                if not mine:
                    detail["errors"].append("no thread found")
                for path, title in mine.items():
                    first = site.get(path)
                    pages = last_page(first, path)
                    done = prev.get(path, {}).get("done_page")
                    start_page = done or first_page_from(site, path, pages, START_DATE, now)
                    info = {"title": title, "pages": pages, "start_page": start_page, "done_page": done}
                    detail["threads"][path] = info
                    end_page = pages if max_pages is None else min(pages, start_page + max_pages - 1)
                    if end_page < pages:
                        detail["errors"].append(f"test run: stopped after {max_pages} pages")
                    for page in range(start_page, end_page + 1):
                        soup = first if page == 1 else site.get(f"{path}/page{page}")
                        posts = parse_posts(soup, now)
                        received += len(posts)
                        i, x, e, o = save_posts(conn, symbol, title, posts, START_DATE)
                        inserted, existing, removed = inserted + i, existing + x, removed + e + o
                        info["done_page"] = page   # a page is done once its posts are saved
            except Blocked as e:
                blocked = True
                detail["errors"].append(f"blocked: {e}")
            except Exception as e:
                detail["errors"].append(f"{type(e).__name__}: {e}")

            status = "error" if detail["errors"] else "success"
            write_log(conn, symbol, status, received, removed, inserted, existing, detail)
            totals["inserted"] += inserted
            totals["existing"] += existing
            pages_read = sum((t["done_page"] or t["start_page"] - 1) - t["start_page"] + 1
                             for t in detail["threads"].values())
            print(f"{symbol:<6} threads: {len(mine)} | pages: {pages_read:>4} | posts: {received:>5} | "
                  f"new: {inserted:>5} | existing: {existing:>5} | {status}"
                  + (f" ({detail['errors'][0]})" if detail["errors"] else ""))
            if blocked:
                print("\nHisse.net is refusing requests. Wait an hour, then run again with --retry-failed.")
                break

        assigned, missing = assign_trading_dates(conn)

    print(f"\nNew posts: {totals['inserted']} | already in database: {totals['existing']} | "
          f"requests: {site.requests}")
    print(f"Trading date assigned: {assigned} | still empty (no price data yet): {missing}")
    print(f"Database: {db_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Collect Hisse.net forum posts for BIST 50 stocks.")
    parser.add_argument("symbols", nargs="*", help="only these stocks (default: all)")
    parser.add_argument("--retry-failed", action="store_true", help="only stocks without a successful run")
    parser.add_argument("--db", type=Path, default=DB_PATH, help="database file")
    parser.add_argument("--max-pages", type=int, help="test run: read at most this many pages per thread")
    parser.add_argument("--check", action="store_true", help="only list the thread(s) found for each stock")
    args = parser.parse_args()
    main([s.upper() for s in args.symbols] or None, db_path=args.db,
         retry_failed=args.retry_failed, max_pages=args.max_pages, check=args.check)
