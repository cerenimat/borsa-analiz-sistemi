"""
Training set for fine-tuning a Turkish BERT sentiment model (İG-12)

The ready-made models (FinTurkBERT, BounTi) do not reach the target on our
texts (see eval_results.md): they do not know the language of KAP notices,
headlines and investor comments. A model fine-tuned on our own texts is
compared with them.

This script draws the texts to be labelled for training:

    news      KAP special-situation notices (ODA) + news headlines
    comments  YouTube comments + Hisse.net forum posts

Only texts that enter the analysis are drawn (text_filter.exclusion), spread
evenly over 2023-2026 like the validation set, with a different seed.

No overlap with the evaluation: every row of the validation files is skipped,
by (source, source_id) and by text (the same headline can come under another id).
Both validation batches must therefore exist before the training set is drawn;
the validation sets stay the human-labelled ground truth and are never trained on.

Labels: column `label` (positive / negative / neutral), column `labeler` says
who labelled the row (e.g. 'llm' or 'human').

The database is opened read-only. Same --seed + same database = same sample.

Run (from the project root):
    python sentiment/make_training_set.py --db data/work.db
Output:
    data/training/train_set.csv
"""
import argparse
import csv
import random
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "sentiment"))
from make_validation_set import OUT as VALIDATION_FILES, labelled_keys, sample_part, text_key  # noqa: E402

OUT = ROOT / "data" / "training" / "train_set.csv"
COLUMNS = ["row", "source", "source_id", "type", "symbols", "published_at", "title", "text", "label", "labeler"]

# part name -> (SQL filter, size)
PARTS = {
    "kap": ("c.type = 'kap' AND c.is_company_notice = 1 AND c.category = 'ODA'", 500),
    "news": ("c.type = 'news'", 500),
    "youtube": ("c.type = 'comment' AND c.source = 'YouTube'", 500),
    "forum": ("c.type = 'comment' AND c.source = 'Hisse.net'", 500),
}


def main(db_path, out, seed, scale):
    if not db_path.exists():
        sys.exit(f"Database not found: {db_path}")
    if out.exists():
        sys.exit(f"{out} already exists; it may hold labels. Move or rename it first.")
    missing = [p for p in VALIDATION_FILES.values() if not p.exists()]
    if missing:
        sys.exit("Validation file(s) missing: " + ", ".join(p.name for p in missing) +
                 "\nCreate both validation batches first, so that no test row can end up in training.")
    skip, skip_texts = labelled_keys(VALIDATION_FILES.values(), with_texts=True)

    rng = random.Random(seed)
    conn = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
    rows, used = [], set(skip_texts)
    for name, (where, size) in PARTS.items():
        part, counts = sample_part(conn, where, round(size * scale), rng, skip, filtered=True, skip_texts=used)
        used |= {text_key(r[5]) for r in part}           # no text twice across parts
        rows += part
        print(f"{name:<8} {len(part):>4}  {counts}")
    conn.close()
    rng.shuffle(rows)

    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(COLUMNS)
        for i, (source, source_id, ctype, published, title, text, _url, symbols, *_) in enumerate(rows, 1):
            w.writerow([i, source, source_id, ctype, symbols, published, title, text, "", ""])
    print(f"\n{len(rows)} rows (validation rows skipped: {len(skip)}) -> {out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Draw the texts to be labelled for fine-tuning.")
    parser.add_argument("--db", type=Path, required=True, help="database with KAP, news, YouTube and forum")
    parser.add_argument("--out", type=Path, default=OUT, help="output .csv")
    parser.add_argument("--seed", type=int, default=7, help="random seed (differs from the validation seed)")
    parser.add_argument("--scale", type=float, default=1.0, help="multiplies every part size (0.1 for a test)")
    args = parser.parse_args()
    main(args.db, args.out, args.seed, args.scale)
