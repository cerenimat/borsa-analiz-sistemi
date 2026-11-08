"""
YouTube comment collector

For each stock in the `stocks` table (BIST 50) searches Turkish YouTube videos
("<SYMBOL> hisse") year by year from 2023 to today, keeps the videos whose title
contains the stock code, and writes their top-level comments to the shared
database (data/borsa.db):

    contents         one row per comment (type = 'comment', source = 'YouTube')
    content_symbols  one row per (comment, stock)
    update_log       one row per stock and run (source = 'youtube')

Afterwards assign_trading_dates() fills empty trading_date fields.

Per requirement İOG-Y-04 (requirements document) no user name, channel or
profile information is stored: only the comment text, its date and its link.

Needs a YouTube Data API v3 key in .env at the project root:
    YOUTUBE_API_KEY=...

Quota: the API gives 10,000 units per day. One search costs 100 units and one
page of up to 100 comments costs 1 unit, so one stock (one search per year)
costs about 450-500 units and all 50 stocks take about three days. When the
quota runs out the run stops; --retry-failed continues the next day with the
stocks that are not finished yet.

Run (from the project root):
    python sentiment/fetch_youtube.py                    # all stocks
    python sentiment/fetch_youtube.py THYAO PGSUS        # only these stocks
    python sentiment/fetch_youtube.py --retry-failed     # stocks without a successful run
    python sentiment/fetch_youtube.py --db data/test.db  # another database file
"""
import argparse
import html
import json
import re
import sys
import time
from contextlib import closing
from datetime import datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "data_collection"))

from config import DB_PATH, TIMEZONE  # noqa: E402
from database import (assign_trading_dates, connect, create_schema,  # noqa: E402
                      seed_stocks)

START_YEAR = 2023                     # team decision: all sources start on 2023-01-01
MAX_VIDEOS = 20                       # videos per stock and year (title must contain the stock code)
MAX_COMMENTS = 200                    # top-level comments per video
WAIT_SECONDS = 0.2                    # pause between requests
RATE_LIMIT_WAITS = (60, 120)          # seconds to wait after "429 Too Many Requests" before giving up
SOURCE = "YouTube"

API = "https://www.googleapis.com/youtube/v3"
VIDEO_URL = "https://www.youtube.com/watch?v={}"
COMMENT_URL = "https://www.youtube.com/watch?v={}&lc={}"

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
VALUES ('youtube', ?, ?, ?, ?, ?, ?, ?, ?)
"""


class QuotaExceeded(Exception):
    """The daily YouTube API quota is used up; continue tomorrow with --retry-failed."""


class CommentsDisabled(Exception):
    """The video does not allow comments; it is skipped."""


def load_api_key():
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key.strip() == "YOUTUBE_API_KEY" and value.strip():
                return value.strip().strip('"').strip("'")
    sys.exit("YOUTUBE_API_KEY not found. Copy .env.example to .env and write your key in it.")


def safe_error(e, api_key):
    """Error text without the request URL and the API key (it must never reach the database)."""
    text = f"{type(e).__name__}: {e}".split(" for url:")[0]
    return text.replace(api_key, "***") if api_key else text


def scrub_logs(conn, api_key):
    """Removes the API key from update_log rows written by older versions of this script."""
    with conn:
        conn.execute("UPDATE update_log SET detail = replace(detail, ?, '***') "
                     "WHERE source = 'youtube' AND instr(detail, ?) > 0", (api_key, api_key))


def api_get(endpoint, params, api_key):
    """GET request to the YouTube Data API; maps quota / disabled-comment errors to exceptions."""
    too_many = 0
    for attempt in range(1, 4):
        try:
            r = requests.get(f"{API}/{endpoint}", params={**params, "key": api_key}, timeout=30)
        except requests.RequestException:
            if attempt == 3:
                raise
            time.sleep(2 * attempt)
            continue
        if r.status_code == 429:
            # YouTube answers 429 when the quota / request rate is exhausted:
            # wait once or twice, then treat it as an exhausted quota and stop the run.
            too_many += 1
            if too_many > len(RATE_LIMIT_WAITS):
                raise QuotaExceeded("429 Too Many Requests")
            print(f"  YouTube: too many requests; waiting {RATE_LIMIT_WAITS[too_many - 1]} s ...")
            time.sleep(RATE_LIMIT_WAITS[too_many - 1])
            continue
        if r.status_code == 403:
            reasons = {e.get("reason") for e in r.json().get("error", {}).get("errors", [])}
            if reasons & {"quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded"}:
                raise QuotaExceeded(", ".join(sorted(reasons)))
            if "commentsDisabled" in reasons:
                raise CommentsDisabled()
        if r.status_code >= 500 and attempt < 3:
            time.sleep(2 * attempt)
            continue
        r.raise_for_status()
        time.sleep(WAIT_SECONDS)
        return r.json()
    raise QuotaExceeded("429 Too Many Requests")


def years():
    """START_YEAR .. current year; each year is searched separately so that older
    years are not crowded out by recent videos (relevance search favours new ones)."""
    return list(range(START_YEAR, datetime.now(TIMEZONE).year + 1))


def find_videos(symbol, year, api_key):
    """Returns up to MAX_VIDEOS [(video_id, title)] published in `year` whose title contains the stock code."""
    data = api_get("search", {
        "part": "snippet", "q": f"{symbol} hisse", "type": "video", "maxResults": 50,
        "order": "relevance",
        "publishedAfter": f"{year}-01-01T00:00:00Z", "publishedBefore": f"{year + 1}-01-01T00:00:00Z",
        "relevanceLanguage": "tr", "regionCode": "TR",
    }, api_key)
    code = re.compile(rf"\b{re.escape(symbol)}\b", re.IGNORECASE)
    videos = []
    for item in data.get("items", []):
        title = html.unescape(item["snippet"]["title"])   # search API returns "&#39;" etc.
        if code.search(title):
            videos.append((item["id"]["videoId"], title))
    return videos[:MAX_VIDEOS]


def fetch_comments(video_id, api_key):
    """Returns up to MAX_COMMENTS top-level comment snippets of a video (newest first)."""
    comments, page = [], None
    while len(comments) < MAX_COMMENTS:
        params = {"part": "snippet", "videoId": video_id, "maxResults": 100,
                  "order": "time", "textFormat": "plainText"}
        if page:
            params["pageToken"] = page
        data = api_get("commentThreads", params, api_key)
        for item in data.get("items", []):
            top = item["snippet"]["topLevelComment"]
            comments.append((top["id"], top["snippet"]))
        page = data.get("nextPageToken")
        if not page:
            break
    return comments[:MAX_COMMENTS]


def to_content(video_id, video_title, comment_id, snippet):
    """Converts one comment to the values of INSERT_CONTENT (no author data, İOG-Y-04)."""
    text = (snippet.get("textOriginal") or snippet.get("textDisplay") or "").strip()
    if not text:
        raise ValueError("empty comment")
    published = datetime.fromisoformat(snippet["publishedAt"].replace("Z", "+00:00"))
    published = published.astimezone(TIMEZONE).isoformat(timespec="seconds")
    return (SOURCE, video_title, text, COMMENT_URL.format(video_id, comment_id),
            published, comment_id)


def save_comments(conn, symbol, video_id, video_title, comments):
    """Writes one video's comments in one transaction; returns (inserted, existing, skipped)."""
    inserted = existing = skipped = 0
    with conn:
        for comment_id, snippet in comments:
            try:
                row = to_content(video_id, video_title, comment_id, snippet)
            except Exception:
                skipped += 1
                continue
            cur = conn.execute(INSERT_CONTENT, row)
            if cur.rowcount:
                inserted += 1
            else:
                existing += 1
            # A video can be found for more than one stock; the link is written in any case.
            content_id = conn.execute(FIND_CONTENT, (SOURCE, comment_id)).fetchone()[0]
            conn.execute(INSERT_LINK, (content_id, symbol))
    return inserted, existing, skipped


def write_log(conn, symbol, status, received, skipped, inserted, existing, detail):
    run_at = datetime.now(TIMEZONE).isoformat(timespec="seconds")
    with conn:
        conn.execute(INSERT_LOG, (symbol, run_at, status, received, skipped,
                                  inserted, existing, json.dumps(detail, ensure_ascii=False)))


def latest_runs(conn):
    """{symbol: (status, detail)} of each stock's latest 'youtube' run."""
    rows = conn.execute(
        "SELECT symbol, status, detail FROM update_log u WHERE source = 'youtube' AND id = "
        "(SELECT MAX(id) FROM update_log WHERE source = 'youtube' AND symbol = u.symbol)"
    ).fetchall()
    return {s: (status, json.loads(detail or "{}")) for s, status, detail in rows}


def main(symbols=None, db_path=DB_PATH, retry_failed=False):
    api_key = load_api_key()
    with closing(connect(db_path)) as conn:
        create_schema(conn)
        seed_stocks(conn)   # content_symbols needs the stocks table
        scrub_logs(conn, api_key)
        stocks = [s for (s,) in conn.execute("SELECT symbol FROM stocks ORDER BY symbol")]
        if symbols:
            unknown = set(symbols) - set(stocks)
            if unknown:
                sys.exit(f"Unknown symbols: {', '.join(sorted(unknown))}")
            stocks = [s for s in stocks if s in symbols]
        runs = latest_runs(conn) if retry_failed else {}
        if retry_failed:
            stocks = [s for s in stocks if runs.get(s, ("", {}))[0] != "success"]
            print(f"{len(stocks)} stocks without a successful run\n")

        totals = {"videos": 0, "inserted": 0, "existing": 0, "skipped": 0}
        quota_hit = False
        for symbol in stocks:
            received = inserted = existing = skipped = 0
            # With --retry-failed, years finished in the previous (interrupted) run are not searched again.
            prev = runs.get(symbol, ("", {}))[1]
            completed = list(prev.get("completed_years", []))
            per_year = {int(y): n for y, n in prev.get("videos_per_year", {}).items()
                        if int(y) in completed}
            seen = set(prev.get("videos", [])) if completed else set()
            new_videos, disabled, errors = [], [], []
            year = None
            try:
                for year in years():
                    if year in completed:
                        continue
                    found = [v for v in find_videos(symbol, year, api_key) if v[0] not in seen]
                    for video_id, title in found:
                        try:
                            comments = fetch_comments(video_id, api_key)
                        except CommentsDisabled:
                            disabled.append(video_id)
                            continue
                        except QuotaExceeded:
                            raise
                        except Exception as e:
                            errors.append(f"{video_id}: {safe_error(e, api_key)}")
                            continue
                        received += len(comments)
                        i, x, s = save_comments(conn, symbol, video_id, title, comments)
                        inserted, existing, skipped = inserted + i, existing + x, skipped + s
                    seen |= {v for v, _ in found}
                    new_videos += [v for v, _ in found]
                    per_year[year] = len(found)
                    completed.append(year)   # year finished: its comments are saved
            except QuotaExceeded as e:
                quota_hit = True
                errors.append(f"{year}: quota exceeded ({safe_error(e, api_key)})")
            except Exception as e:
                errors.append(f"{year}: search: {safe_error(e, api_key)}")

            videos = new_videos
            status = "error" if errors else "success"
            detail = {"completed_years": completed, "videos_per_year": per_year,
                      "videos": sorted(seen), "comments_disabled": disabled, "errors": errors[:20]}
            write_log(conn, symbol, status, received, skipped, inserted, existing, detail)
            totals["videos"] += len(videos)
            totals["inserted"] += inserted
            totals["existing"] += existing
            totals["skipped"] += skipped
            years_text = " ".join(f"{y}:{n}" for y, n in per_year.items())
            print(f"{symbol:<6} videos: {len(videos):>3} ({years_text}) | comments: {received:>5} | "
                  f"new: {inserted:>5} | existing: {existing:>5} | skipped: {skipped} | {status}")
            if quota_hit:
                print("\nYouTube API daily quota is used up. Run again tomorrow with --retry-failed.")
                break

        assigned, missing = assign_trading_dates(conn)

    print(f"\nVideos: {totals['videos']} | new comments: {totals['inserted']} | "
          f"already in database: {totals['existing']} | skipped (empty): {totals['skipped']}")
    print(f"Trading date assigned: {assigned} | still empty (no price data yet): {missing}")
    print(f"Database: {db_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Collect YouTube comments for BIST 50 stocks.")
    parser.add_argument("symbols", nargs="*", help="only these stocks (default: all)")
    parser.add_argument("--retry-failed", action="store_true",
                        help="only stocks without a successful run")
    parser.add_argument("--db", type=Path, default=DB_PATH, help="database file")
    args = parser.parse_args()
    main([s.upper() for s in args.symbols] or None, db_path=args.db, retry_failed=args.retry_failed)
