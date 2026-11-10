"""
Export sentiment scores into a small database for the shared database

Scoring needs the fine-tuned model (data/models/berturk-sentiment, ~440 MB),
which is not in Git; it runs on one machine (score_contents.py) and the scores
reach the shared database through this export and merge_sources.py.

The export is a schema v2 database holding, for one model:
    sentiments       the scores
    contents         the scored contents (merge_sources matches them in the
                     target by source + source_id, so ids may differ)
    content_symbols  their stock links
    stocks           the stock list (needed by the links)

The source database is opened read-only; an existing output file is not
overwritten.

Run (from the project root):
    python sentiment/export_sentiments.py --db data/work.db
    python sentiment/merge_sources.py data/sentiments_berturk.db --target data/borsa.db
Output:
    data/sentiments_berturk.db
"""
import argparse
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "data_collection"))
from config import DATA_DIR, SCHEMA_PATH  # noqa: E402

DEFAULT_MODEL = "BERTurk"


def columns(conn, table, schema="main"):
    return [row[1] for row in conn.execute(f"PRAGMA {schema}.table_info({table})")]


def main(db_path, out_path, model):
    if not db_path.exists():
        sys.exit(f"Database not found: {db_path}")
    if out_path.exists():
        sys.exit(f"Output already exists: {out_path} (remove it or choose another --out)")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(out_path)) as out:
        out.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        out.execute("ATTACH DATABASE ? AS src", (f"file:{db_path.resolve()}?mode=ro",))
        for table in ("stocks", "contents", "content_symbols", "sentiments"):
            if columns(out, table) != columns(out, table, "src"):
                sys.exit(f"Table '{table}' of {db_path.name} differs from schema.sql; schema versions do not match.")
        n = out.execute("SELECT COUNT(*) FROM src.sentiments WHERE model = ?", (model,)).fetchone()[0]
        if not n:
            sys.exit(f"No '{model}' rows in {db_path.name} (run sentiment/score_contents.py first)")

        scored = "SELECT content_id FROM src.sentiments WHERE model = ?"
        stock_cols = ", ".join(columns(out, "stocks"))
        content_cols = ", ".join(columns(out, "contents"))
        out.execute(f"INSERT INTO stocks ({stock_cols}) SELECT {stock_cols} FROM src.stocks")
        out.execute(f"INSERT INTO contents ({content_cols}) SELECT {content_cols} FROM src.contents "
                    f"WHERE id IN ({scored})", (model,))
        out.execute(f"INSERT INTO content_symbols (content_id, symbol) SELECT content_id, symbol "
                    f"FROM src.content_symbols WHERE content_id IN ({scored})", (model,))
        out.execute("INSERT INTO sentiments (content_id, model, label, score) "
                    "SELECT content_id, model, label, score FROM src.sentiments WHERE model = ?", (model,))
        out.commit()
        out.execute("DETACH DATABASE src")
        summary = out.execute("""SELECT c.type, COUNT(*) FROM sentiments s
                                 JOIN contents c ON c.id = s.content_id GROUP BY c.type""").fetchall()
        bad = out.execute("PRAGMA foreign_key_check").fetchall()
        out.execute("VACUUM")
    print(f"{model}: {n} scores exported {dict(summary)} | foreign key problems: {len(bad)}")
    print(f"Output: {out_path} ({out_path.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export one model's sentiment scores for merging.")
    parser.add_argument("--db", type=Path, required=True, help="scored database (e.g. data/work.db)")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"sentiments.model value (default {DEFAULT_MODEL})")
    parser.add_argument("--out", type=Path, help="output file (default data/sentiments_<model>.db)")
    args = parser.parse_args()
    main(args.db, args.out or DATA_DIR / f"sentiments_{args.model.lower()}.db", args.model)
