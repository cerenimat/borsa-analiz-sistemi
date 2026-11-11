"""
Score all collected texts with the fine-tuned sentiment model (İG-12 / İG-13)

Every content that enters the analysis (text_filter.exclusion) gets one row in
`sentiments` for the model:

    label   positive / negative / neutral   (class with the highest probability)
    score   P(positive) - P(negative), between -1 and +1

Texts left out by text_filter get no row (they stay in `contents`). The model
is data/models/berturk-sentiment (train_model.py output); input texts are
cleaned with text_filter.clean_text and cut at 128 tokens, as in training.

Resumable: only contents without a row for this model are scored and the work
is committed in chunks, so an interrupted run continues where it stopped.
After the model is retrained, --rescore removes the model's rows first.

Run (from the project root):
    python sentiment/score_contents.py --db data/work.db --dry-run     # counts only
    python sentiment/score_contents.py --db data/work.db --limit 2000  # short test
    python sentiment/score_contents.py --db data/work.db
"""
import argparse
import sqlite3
import sys
import time
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "sentiment"))
from text_filter import clean_text, exclusion  # noqa: E402

MODEL_DIR = ROOT / "data" / "models" / "berturk-sentiment"
MODEL_NAME = "BERTurk"          # value of sentiments.model (see schema.sql)
LABELS = ["negative", "neutral", "positive"]
MAX_LENGTH = 128
BATCH_SIZE = 32
CHUNK = 2000                    # texts per commit

PENDING = """
SELECT c.id, c.type, c.category, c.is_company_notice, c.text, c.source
FROM contents c
LEFT JOIN sentiments s ON s.content_id = c.id AND s.model = ?
WHERE s.id IS NULL
ORDER BY c.id
"""
INSERT = "INSERT OR IGNORE INTO sentiments (content_id, model, label, score) VALUES (?, ?, ?, ?)"


def pending(conn):
    """(to_score [(id, type, text)], excluded {reason: count}) for contents without a row."""
    to_score, excluded = [], {}
    for cid, ctype, category, notice, text, source in conn.execute(PENDING, (MODEL_NAME,)):
        reason = exclusion(ctype, category, notice, text, source)
        if reason is None and not clean_text(text):
            reason = "empty"
        if reason:
            key = f"{ctype}: {reason}"
            excluded[key] = excluded.get(key, 0) + 1
        else:
            to_score.append((cid, ctype, text))
    return to_score, excluded


def load_model():
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    if not (MODEL_DIR / "config.json").exists():
        sys.exit(f"Model not found: {MODEL_DIR} (run sentiment/train_model.py first)")
    if torch.backends.mps.is_available():
        dev = torch.device("mps")                     # Apple silicon
    elif torch.cuda.is_available():
        dev = torch.device("cuda")
    else:
        dev = torch.device("cpu")
    tok = AutoTokenizer.from_pretrained(MODEL_DIR)
    model = AutoModelForSequenceClassification.from_pretrained(MODEL_DIR).to(dev).eval()
    labels = [model.config.id2label[i].lower() for i in range(model.config.num_labels)]
    if sorted(labels) != sorted(LABELS):
        sys.exit(f"Unexpected model labels: {labels}")
    return torch, tok, model, labels, dev


def score_chunk(torch, tok, model, labels, dev, rows):
    """[(content_id, label, score)] for rows [(id, type, text)]."""
    rows = sorted(rows, key=lambda r: len(r[2]))      # similar lengths -> less padding
    out = []
    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i:i + BATCH_SIZE]
        enc = tok([clean_text(r[2]) for r in batch], return_tensors="pt",
                  truncation=True, max_length=MAX_LENGTH, padding=True).to(dev)
        with torch.no_grad():
            probs = torch.softmax(model(**enc).logits, dim=-1).cpu().tolist()
        for r, p in zip(batch, probs):
            prob = dict(zip(labels, p))
            score = max(-1.0, min(1.0, prob["positive"] - prob["negative"]))
            out.append((r[0], max(prob, key=prob.get), round(score, 4)))
    return out


def summary(conn):
    rows = conn.execute("""
        SELECT c.type, s.label, COUNT(*), ROUND(AVG(s.score), 3)
        FROM sentiments s JOIN contents c ON c.id = s.content_id
        WHERE s.model = ? GROUP BY c.type, s.label ORDER BY c.type, s.label""", (MODEL_NAME,)).fetchall()
    print("\nRows in sentiments for", MODEL_NAME)
    for ctype, label, n, avg in rows:
        print(f"  {ctype:<8} {label:<9} {n:>7}  avg score {avg:+.3f}")


def main(db_path, dry_run=False, limit=None, rescore=False):
    if not db_path.exists():
        sys.exit(f"Database not found: {db_path}")
    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        if rescore and not dry_run:
            n = conn.execute("DELETE FROM sentiments WHERE model = ?", (MODEL_NAME,)).rowcount
            conn.commit()
            print(f"--rescore: removed {n} earlier {MODEL_NAME} rows")

        to_score, excluded = pending(conn)
        print(f"Contents without a {MODEL_NAME} row: {len(to_score) + sum(excluded.values())}")
        print(f"  left out by text_filter: {sum(excluded.values())}")
        for key, n in sorted(excluded.items()):
            print(f"    {key:<32} {n:>7}")
        by_type = {}
        for _, ctype, _ in to_score:
            by_type[ctype] = by_type.get(ctype, 0) + 1
        print(f"  to score: {len(to_score)} {by_type}")
        if limit:
            to_score = to_score[:limit]
            print(f"  --limit: scoring the first {len(to_score)}")
        if dry_run or not to_score:
            summary(conn)
            return

        torch, tok, model, labels, dev = load_model()
        print(f"\nModel: {MODEL_DIR.name}, device: {dev}\n")
        start, done = time.time(), 0
        for i in range(0, len(to_score), CHUNK):
            result = score_chunk(torch, tok, model, labels, dev, to_score[i:i + CHUNK])
            conn.executemany(INSERT, [(cid, MODEL_NAME, lab, sc) for cid, lab, sc in result])
            conn.commit()
            done += len(result)
            rate = done / (time.time() - start)
            left = (len(to_score) - done) / rate if rate else 0
            print(f"  {done:>7}/{len(to_score)}  {rate:6.0f} texts/s  ~{left / 60:5.1f} min left", flush=True)
        print(f"\nDone in {(time.time() - start) / 60:.1f} min.")
        summary(conn)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Score collected texts with the fine-tuned sentiment model.")
    parser.add_argument("--db", type=Path, required=True, help="database to score (e.g. data/work.db)")
    parser.add_argument("--dry-run", action="store_true", help="only count what would be scored")
    parser.add_argument("--limit", type=int, help="score at most this many texts (for a test run)")
    parser.add_argument("--rescore", action="store_true", help="remove this model's rows first (after retraining)")
    args = parser.parse_args()
    main(args.db, args.dry_run, args.limit, args.rescore)
