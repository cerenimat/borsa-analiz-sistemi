"""
Update the sentiment data in one command

Runs the four collectors in update mode on the working database, scores the
new texts and exports only what is new into a small file for the shared
database:

    1. fetch_kap.py, fetch_news.py, fetch_youtube.py --update
       (each stock from its last successful run minus a few days, see incremental.py)
    2. fetch_forum.py (always incremental: each thread from its last page)
    3. score_contents.py (texts without a score; needs the model in data/models/)
    4. export: contents added by this run, their stock links and scores, and the
       update_log rows of this run -> data/updates/update_<date>_<time>.db

A collector that fails (no network, YouTube quota, Google refusing requests)
is reported and the others still run; the next update starts that collector
from its own last successful run again, so nothing is lost.

The export is merged into the shared database with merge_sources.py; contents
already in the target are skipped, so merging the same file twice is safe.

Run (from the project root):
    python sentiment/update_sentiment.py                       # all sources, data/work.db
    python sentiment/update_sentiment.py --skip youtube        # without YouTube (quota)
    python sentiment/update_sentiment.py --since 2026-11-01    # every source from this date
Then, on the shared database:
    python sentiment/merge_sources.py data/updates/update_<...>.db --target data/borsa.db
"""
import argparse
import sqlite3
import sys
import time
import traceback
from contextlib import closing
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "data_collection"))
sys.path.insert(0, str(ROOT / "sentiment"))
from config import SCHEMA_PATH, TIMEZONE  # noqa: E402

DEFAULT_DB = ROOT / "data" / "work.db"
OUT_DIR = ROOT / "data" / "updates"
SOURCES = ("kap", "news", "youtube", "forum")


def run_collector(name, db_path, since):
    """Runs one collector in update mode; returns None or an error text."""
    print(f"\n{'=' * 20} {name} {'=' * 20}", flush=True)
    try:
        if name == "kap":
            import fetch_kap
            fetch_kap.main(db_path=db_path, update=True, since=since)
        elif name == "news":
            import fetch_news
            fetch_news.main(db_path=db_path, update=True, since=since)
        elif name == "youtube":
            import fetch_youtube
            fetch_youtube.main(db_path=db_path, update=True, since=since)
        elif name == "forum":
            import fetch_forum
            fetch_forum.main(db_path=db_path)
    except SystemExit as e:                  # collectors stop with sys.exit(message), e.g. no API key
        return str(e.code)
    except Exception as e:
        traceback.print_exc()
        return f"{type(e).__name__}: {e}"
    return None


def export_new(db_path, out_path, before_content, before_score, started):
    """Writes contents with id > before_content, scores with id > before_score (with their
    contents) and this run's update_log rows into a new schema v2 database."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(out_path, uri=True)) as out:   # uri=True: ATTACH below uses ?mode=ro
        out.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        out.execute("ATTACH DATABASE ? AS src", (f"file:{db_path.resolve()}?mode=ro",))

        def cols(table):
            return ", ".join(r[1] for r in out.execute(f"PRAGMA main.table_info({table})"))
        wanted = ("SELECT id FROM src.contents WHERE id > ? "
                  "UNION SELECT content_id FROM src.sentiments WHERE id > ?")
        args = (before_content, before_score)
        out.execute(f"INSERT INTO stocks ({cols('stocks')}) SELECT {cols('stocks')} FROM src.stocks")
        out.execute(f"INSERT INTO contents ({cols('contents')}) SELECT {cols('contents')} "
                    f"FROM src.contents WHERE id IN ({wanted})", args)
        out.execute(f"INSERT INTO content_symbols (content_id, symbol) SELECT content_id, symbol "
                    f"FROM src.content_symbols WHERE content_id IN ({wanted})", args)
        out.execute("INSERT INTO sentiments (content_id, model, label, score) "
                    "SELECT content_id, model, label, score FROM src.sentiments WHERE id > ?", (before_score,))
        log_cols = ", ".join(c for c in cols("update_log").split(", ") if c != "id")
        out.execute(f"INSERT INTO update_log ({log_cols}) SELECT {log_cols} FROM src.update_log "
                    f"WHERE run_at >= ?", (started,))
        out.commit()
        out.execute("DETACH DATABASE src")
        types = dict(out.execute("SELECT type, COUNT(*) FROM contents GROUP BY type").fetchall())
        scores = out.execute("SELECT COUNT(*) FROM sentiments").fetchone()[0]
        logs = out.execute("SELECT COUNT(*) FROM update_log").fetchone()[0]
        out.execute("VACUUM")
    return types, scores, logs


def main(db_path, skip=(), since=None, score=True):
    if not db_path.exists():
        sys.exit(f"Database not found: {db_path}")
    started = datetime.now(TIMEZONE).isoformat(timespec="seconds")
    with closing(sqlite3.connect(db_path)) as conn:
        before_content = conn.execute("SELECT COALESCE(MAX(id), 0) FROM contents").fetchone()[0]
        before_score = conn.execute("SELECT COALESCE(MAX(id), 0) FROM sentiments").fetchone()[0]

    t0 = time.time()
    failures = {}
    for name in SOURCES:
        if name in skip:
            print(f"\n{name}: skipped (--skip)")
            continue
        error = run_collector(name, db_path, since)
        if error:
            failures[name] = error

    if score:
        print(f"\n{'=' * 20} scoring {'=' * 20}", flush=True)
        import score_contents
        score_contents.main(db_path)

    stamp = datetime.now(TIMEZONE).strftime("%Y-%m-%d_%H%M")
    out_path = OUT_DIR / f"update_{stamp}.db"
    types, scores, logs = export_new(db_path, out_path, before_content, before_score, started)

    print(f"\n{'=' * 20} summary {'=' * 20}")
    print(f"New contents: {sum(types.values())} {types} | new scores: {scores} | log rows: {logs}")
    for name, error in failures.items():
        print(f"  {name}: FAILED ({error}) - the next update starts it from its last successful run")
    print(f"Time: {(time.time() - t0) / 60:.1f} min")
    print(f"Output: {out_path} ({out_path.stat().st_size / 1e6:.1f} MB)")
    print(f"Shared database: python sentiment/merge_sources.py {out_path.relative_to(ROOT)} "
          f"--target data/borsa.db")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Collect, score and export new sentiment data.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="working database (default data/work.db)")
    parser.add_argument("--skip", nargs="+", choices=SOURCES, default=(), help="sources to leave out")
    parser.add_argument("--since", type=date.fromisoformat, help="start every source from this date")
    parser.add_argument("--no-score", action="store_true", help="collect and export without scoring")
    args = parser.parse_args()
    main(args.db, skip=set(args.skip), since=args.since, score=not args.no_score)
