"""
Merge collected sources into the shared database

YouTube comments and news headlines are collected into their own database
files (data/youtube.db, data/google_news.db): the YouTube API has a daily
quota and search results change over time, so re-running those collectors on
the shared database would cost days and would not return the same data.
This script copies their content into the shared database instead.

For every source database:
    contents         copied; a row that already exists in the target
                     (same source + source_id) is not copied again
    content_symbols  copied, with content ids translated to the target's ids
    update_log       copied (same source + symbol + run_at is not copied twice),
                     so the collection method and dates stay documented
    sentiments       copied with translated content ids; a score the target
                     already has for the same content and model is replaced
                     (scores come from export_sentiments.py, e.g.
                     data/sentiments_berturk.db, after the model was re-run)
Afterwards assign_trading_dates() fills empty trading_date fields from the
target's prices.

Forum posts (data/hissenet.db) are logged with update_log.source = 'forum',
which schema v2 does not allow yet; the target's update_log table is then
rebuilt with 'forum' added (see fetch_forum.ensure_forum_source). --dry-run
only reports this.

Source databases are opened read-only. Running the script twice is safe.

Run (from the project root):
    python sentiment/merge_sources.py --target data/borsa.db --dry-run   # only report
    python sentiment/merge_sources.py --target data/borsa.db             # merge
    python sentiment/merge_sources.py --target data/borsa.db data/youtube.db   # one source
    python sentiment/merge_sources.py --target data/borsa.db data/sentiments_berturk.db   # scores
"""
import argparse
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "data_collection"))

from config import DB_PATH, DATA_DIR  # noqa: E402
from database import assign_trading_dates, connect, create_schema  # noqa: E402

DEFAULT_SOURCES = [DATA_DIR / "google_news.db", DATA_DIR / "youtube.db"]


def allows_forum(conn):
    sql = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'update_log'").fetchone()[0]
    return "'forum'" in sql


def columns(conn, table):
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]


def open_read_only(path):
    if not path.exists():
        sys.exit(f"Source database not found: {path}")
    return sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)


def check_compatible(src, tgt, path):
    """Both databases must have the same contents / update_log columns (schema v2)."""
    for table in ("contents", "content_symbols", "update_log", "sentiments"):
        if columns(src, table) != columns(tgt, table):
            sys.exit(f"{path.name}: table '{table}' differs from the target; schema versions do not match.")


def merge_contents(src, tgt):
    """Copies contents and returns {source id: target id} plus (inserted, existing)."""
    cols = [c for c in columns(tgt, "contents") if c not in ("id", "trading_date")]
    insert = (f"INSERT INTO contents ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))}) "
              "ON CONFLICT (source, source_id) DO NOTHING")
    find = "SELECT id FROM contents WHERE source = ? AND source_id = ?"
    i_source, i_source_id = cols.index("source"), cols.index("source_id")

    id_map, inserted, existing = {}, 0, 0
    for row in src.execute(f"SELECT id, {', '.join(cols)} FROM contents ORDER BY id"):
        src_id, values = row[0], row[1:]
        if tgt.execute(insert, values).rowcount:
            inserted += 1
        else:
            existing += 1
        id_map[src_id] = tgt.execute(find, (values[i_source], values[i_source_id])).fetchone()[0]
    return id_map, inserted, existing


def merge_links(src, tgt, id_map):
    known = {s for (s,) in tgt.execute("SELECT symbol FROM stocks")}
    added = 0
    for content_id, symbol in src.execute("SELECT content_id, symbol FROM content_symbols"):
        if symbol not in known:
            sys.exit(f"Symbol {symbol} is not in the target's stocks table.")
        added += tgt.execute("INSERT OR IGNORE INTO content_symbols (content_id, symbol) VALUES (?, ?)",
                             (id_map[content_id], symbol)).rowcount
    return added


def merge_sentiments(src, tgt, id_map):
    """Copies scores; returns (added, replaced). A changed score for the same content and model
    (the model was re-run) replaces the target's row; an identical one is left alone."""
    find = "SELECT label, score FROM sentiments WHERE content_id = ? AND model = ?"
    added = replaced = 0
    for content_id, model, label, score in src.execute(
            "SELECT content_id, model, label, score FROM sentiments ORDER BY id"):
        target_id = id_map[content_id]
        old = tgt.execute(find, (target_id, model)).fetchone()
        if old is None:
            tgt.execute("INSERT INTO sentiments (content_id, model, label, score) VALUES (?, ?, ?, ?)",
                        (target_id, model, label, score))
            added += 1
        elif old != (label, score):
            tgt.execute("UPDATE sentiments SET label = ?, score = ? WHERE content_id = ? AND model = ?",
                        (label, score, target_id, model))
            replaced += 1
    return added, replaced


def merge_logs(src, tgt, count_only=()):
    cols = [c for c in columns(tgt, "update_log") if c != "id"]
    exists = "SELECT 1 FROM update_log WHERE source = ? AND symbol IS ? AND run_at = ?"
    insert = f"INSERT INTO update_log ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})"
    i = {c: cols.index(c) for c in ("source", "symbol", "run_at")}
    copied = 0
    for row in src.execute(f"SELECT {', '.join(cols)} FROM update_log ORDER BY id"):
        if not tgt.execute(exists, (row[i["source"]], row[i["symbol"]], row[i["run_at"]])).fetchone():
            if row[i["source"]] not in count_only:
                tgt.execute(insert, row)
            copied += 1
    return copied


def main(sources, target, dry_run=False):
    if not target.exists():
        sys.exit(f"Target database not found: {target}")
    with closing(connect(target)) as tgt:
        create_schema(tgt)   # creates nothing on a schema v2 database; keeps views in place
        has_forum = False
        for path in sources:
            with closing(open_read_only(path)) as src:
                has_forum |= bool(src.execute(
                    "SELECT 1 FROM update_log WHERE source = 'forum' LIMIT 1").fetchone())
        count_only = ()
        if has_forum and not allows_forum(tgt):
            if dry_run:
                print("note: update_log of the target would get 'forum' as an allowed source\n")
                count_only = ("forum",)
            else:
                from fetch_forum import ensure_forum_source
                ensure_forum_source(tgt)
        for path in sources:
            if path.resolve() == target.resolve():
                sys.exit("A source cannot be the target itself.")
            with closing(open_read_only(path)) as src:
                check_compatible(src, tgt, path)
                types = dict(src.execute("SELECT type, COUNT(*) FROM contents GROUP BY type").fetchall())
                id_map, inserted, existing = merge_contents(src, tgt)
                links = merge_links(src, tgt, id_map)
                logs = merge_logs(src, tgt, count_only)
                scores = merge_sentiments(src, tgt, id_map)
            print(f"{path.name:<16} contents: {sum(types.values()):>6} {types} | new: {inserted:>6} | "
                  f"already in target: {existing:>6} | links added: {links:>6} | log rows: {logs}"
                  + (f" | scores added: {scores[0]}, replaced: {scores[1]}" if any(scores) else ""))

        if dry_run:
            tgt.rollback()
            print("\nDry run: nothing was written to the target.")
            return
        tgt.commit()
        assigned, missing = assign_trading_dates(tgt)
        totals = dict(tgt.execute("SELECT type, COUNT(*) FROM contents GROUP BY type").fetchall())
        scored = dict(tgt.execute("SELECT model, COUNT(*) FROM sentiments GROUP BY model").fetchall())
        bad = tgt.execute("PRAGMA foreign_key_check").fetchall()

    print(f"\nTrading date assigned: {assigned} | still empty (no price data yet): {missing}")
    print(f"Target now holds: {totals} | foreign key problems: {len(bad)}")
    if scored:
        print(f"Sentiment scores: {scored}")
    print(f"Database: {target}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Merge collected source databases into the shared database.")
    parser.add_argument("sources", nargs="*", type=Path, default=DEFAULT_SOURCES,
                        help="source databases (default: data/google_news.db data/youtube.db; "
                             "add data/hissenet.db for forum posts)")
    parser.add_argument("--target", type=Path, default=DB_PATH, help="shared database (default: data/borsa.db)")
    parser.add_argument("--dry-run", action="store_true", help="only report, write nothing")
    args = parser.parse_args()
    main(args.sources, args.target, dry_run=args.dry_run)
