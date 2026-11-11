"""
Evaluate sentiment models on the manually labelled validation set (H3 / İG-15)

Models (ready-made models are applied as they are; BERTurk-FT is added when
train_model.py has produced data/models/berturk-sentiment):
    always_neutral  baseline: predicts the majority class 'neutral' for every text
    FinTurkBERT     ff112/FinTurkBERT - Turkish BERT, further pre-trained on financial
                    text and fine-tuned on a Turkish Financial PhraseBank (3 classes)
    BounTi          akoksal/bounti - BERTurk (uncased) fine-tuned on Turkish tweets (3 classes)

Every model is scored on news (KAP + headlines) and on comments (YouTube + forum)
separately, once on all labelled rows and once on the rows that enter the analysis
(text_filter.exclusion). Reported: accuracy, macro-F1 (each class weighs the same,
so a model cannot score well by predicting 'neutral' only), per-class precision /
recall / F1, confusion matrix, and 95% bootstrap intervals for accuracy and macro-F1
(the sets are small, so single numbers move a lot).

Input texts are cleaned with text_filter.clean_text (İG-11).

Run (from the project root):
    python sentiment/evaluate_models.py --db data/work.db
    python sentiment/evaluate_models.py --db data/work.db --files data/validation/validation_set.xlsx data/validation/validation_set_2.xlsx
Output:
    data/validation/predictions.csv   one row per text and model (label, score, probabilities)
    data/validation/eval_results.md   the result tables
"""
import argparse
import csv
import random
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import torch
from openpyxl import load_workbook
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, precision_recall_fscore_support
from transformers import AutoModelForSequenceClassification, AutoTokenizer

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "sentiment"))
from text_filter import clean_text, exclusion  # noqa: E402

VALIDATION_DIR = ROOT / "data" / "validation"
LABELS = ["negative", "neutral", "positive"]
MAX_LENGTH = 128
BATCH_SIZE = 16
BOOTSTRAP = 1000

# model name -> (Hugging Face id, label of each output index or None to read config.id2label)
MODELS = {
    "FinTurkBERT": ("ff112/FinTurkBERT", ["negative", "neutral", "positive"]),   # per model card
    "BounTi": ("akoksal/bounti", None),
}
FINE_TUNED = ROOT / "data" / "models" / "berturk-sentiment"   # train_model.py output
if (FINE_TUNED / "config.json").exists():
    MODELS["BERTurk-FT"] = (str(FINE_TUNED), None)


def load_rows(files, db_path):
    """Labelled rows of the validation files with the fields text_filter needs."""
    conn = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
    rows = []
    for path in files:
        wb = load_workbook(path, read_only=True)
        for sheet in ("news", "comments"):
            for r in wb[sheet].iter_rows(min_row=2, values_only=True):
                source, source_id, ctype, symbols, published, title, text, label = r[:8]
                if label not in LABELS:
                    sys.exit(f"{path.name}/{sheet}: row {source}/{source_id} has no valid label ({label!r})")
                found = conn.execute("SELECT category, is_company_notice FROM contents "
                                     "WHERE source = ? AND source_id = ?", (source, str(source_id))).fetchone()
                category, notice = found if found else (None, None)
                rows.append({
                    "file": path.name, "group": "news" if sheet == "news" else "comments",
                    "source": source, "source_id": str(source_id), "type": ctype,
                    "text": text or "", "label": label,
                    "analysed": exclusion(ctype, category, notice, text, source) is None,
                })
    conn.close()
    return rows


def device():
    if torch.backends.mps.is_available():
        return torch.device("mps")                    # Apple silicon
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def predict(model_id, labels, texts):
    """[(label, score, {class: probability})] ; score = P(positive) - P(negative)."""
    dev = device()
    tok = AutoTokenizer.from_pretrained(model_id)
    model = AutoModelForSequenceClassification.from_pretrained(model_id).to(dev).eval()
    if labels is None:
        labels = [model.config.id2label[i].lower() for i in range(model.config.num_labels)]
    if sorted(labels) != sorted(LABELS):
        sys.exit(f"{model_id}: unexpected labels {labels}")
    out = []
    for i in range(0, len(texts), BATCH_SIZE):
        batch = [clean_text(t) for t in texts[i:i + BATCH_SIZE]]
        enc = tok(batch, return_tensors="pt", truncation=True, max_length=MAX_LENGTH, padding=True).to(dev)
        with torch.no_grad():
            probs = torch.softmax(model(**enc).logits, dim=-1).cpu().tolist()
        for p in probs:
            prob = dict(zip(labels, p))
            out.append((max(prob, key=prob.get), prob["positive"] - prob["negative"], prob))
    return out


def bootstrap(y_true, y_pred, rng):
    n = len(y_true)
    accs, f1s = [], []
    for _ in range(BOOTSTRAP):
        idx = [rng.randrange(n) for _ in range(n)]
        t, p = [y_true[i] for i in idx], [y_pred[i] for i in idx]
        accs.append(accuracy_score(t, p))
        f1s.append(f1_score(t, p, labels=LABELS, average="macro", zero_division=0))
    q = lambda v: (sorted(v)[int(0.025 * BOOTSTRAP)], sorted(v)[int(0.975 * BOOTSTRAP) - 1])
    return q(accs), q(f1s)


def report(rows, preds, out_md):
    rng = random.Random(42)
    lines = [f"# Duygu modeli değerlendirmesi ({datetime.now():%Y-%m-%d %H:%M})", "",
             f"Dosyalar: {', '.join(sorted({r['file'] for r in rows}))}", ""]
    summary = ["| Grup | Kapsam | n | Model | Doğruluk [95% GA] | Makro-F1 [95% GA] |",
               "|---|---|---|---|---|---|"]
    details = []
    for group in ("news", "comments"):
        for scope in ("all", "analysed"):
            idx = [i for i, r in enumerate(rows) if r["group"] == group and (scope == "all" or r["analysed"])]
            if not idx:
                continue
            y_true = [rows[i]["label"] for i in idx]
            dist = {l: y_true.count(l) for l in LABELS}
            for name, pred in preds.items():
                y_pred = [pred[i][0] for i in idx]
                acc = accuracy_score(y_true, y_pred)
                f1 = f1_score(y_true, y_pred, labels=LABELS, average="macro", zero_division=0)
                (a_lo, a_hi), (f_lo, f_hi) = bootstrap(y_true, y_pred, rng)
                summary.append(f"| {group} | {scope} | {len(idx)} | {name} | {acc:.3f} [{a_lo:.2f}–{a_hi:.2f}] "
                               f"| {f1:.3f} [{f_lo:.2f}–{f_hi:.2f}] |")
                p, r, f, s = precision_recall_fscore_support(y_true, y_pred, labels=LABELS, zero_division=0)
                cm = confusion_matrix(y_true, y_pred, labels=LABELS)
                details += [f"### {group} / {scope} / {name}", "",
                            f"Gerçek dağılım: {dist}", "",
                            "| Sınıf | Kesinlik | Duyarlılık | F1 | n |", "|---|---|---|---|---|"]
                details += [f"| {l} | {p[k]:.2f} | {r[k]:.2f} | {f[k]:.2f} | {s[k]} |" for k, l in enumerate(LABELS)]
                details += ["", "Karışıklık matrisi (satır = gerçek, sütun = tahmin; negative, neutral, positive):",
                            "", "| | " + " | ".join(LABELS) + " |", "|---|---|---|---|"]
                details += [f"| {l} | " + " | ".join(str(x) for x in cm[k]) + " |" for k, l in enumerate(LABELS)]
                details.append("")
    text = "\n".join(lines + ["## Özet", ""] + summary + ["", "## Ayrıntılar", ""] + details)
    out_md.write_text(text, encoding="utf-8")
    print("\n".join(summary))
    print(f"\nDetails: {out_md}")


def main(files, db_path, out_dir):
    rows = load_rows(files, db_path)
    texts = [r["text"] for r in rows]
    print(f"{len(rows)} labelled rows ({sum(r['analysed'] for r in rows)} enter the analysis); device: {device()}\n")
    preds = {"always_neutral": [("neutral", 0.0, {"negative": 0.0, "neutral": 1.0, "positive": 0.0})] * len(rows)}
    for name, (model_id, labels) in MODELS.items():
        print(f"{name}: {model_id} ...")
        preds[name] = predict(model_id, labels, texts)

    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "predictions.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["file", "group", "source", "source_id", "analysed", "label", "model",
                    "pred", "score", "p_negative", "p_neutral", "p_positive", "text"])
        for i, r in enumerate(rows):
            for name, pred in preds.items():
                lab, score, prob = pred[i]
                w.writerow([r["file"], r["group"], r["source"], r["source_id"], int(r["analysed"]), r["label"],
                            name, lab, f"{score:.4f}", *(f"{prob[l]:.4f}" for l in LABELS), r["text"]])
    report(rows, preds, out_dir / "eval_results.md")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate sentiment models on the validation set.")
    parser.add_argument("--db", type=Path, required=True, help="database with the labelled contents (data/work.db)")
    parser.add_argument("--files", type=Path, nargs="+", default=[VALIDATION_DIR / "validation_set.xlsx"],
                        help="labelled validation files")
    parser.add_argument("--out", type=Path, default=VALIDATION_DIR, help="output folder")
    args = parser.parse_args()
    main(args.files, args.db, args.out)
