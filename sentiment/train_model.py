"""
Fine-tune a Turkish BERT on our labelled training set (İG-12)

Base model: dbmdz/bert-base-turkish-cased (BERTurk), the usual starting point
for Turkish text classification. A 3-class head (negative / neutral / positive)
is trained on data/training/train_set.csv; inputs are cleaned with
text_filter.clean_text exactly as in evaluate_models.py.

Model selection uses a development split taken from the training set
(10 %, stratified), never the validation sets: those stay untouched until
evaluate_models.py measures the finished model on them.

Classes are weighted by inverse frequency, so the model cannot do well by
predicting 'neutral' only.

Run (from the project root):
    python sentiment/train_model.py
    python sentiment/train_model.py --epochs 4 --lr 2e-5
Output (not in git, data/ is ignored):
    data/models/berturk-sentiment/   model + tokenizer + train_info.json
evaluate_models.py picks the model up automatically as 'BERTurk-FT'.
"""
import argparse
import csv
import json
import math
import random
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import torch
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import train_test_split
from transformers import AutoModelForSequenceClassification, AutoTokenizer

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "sentiment"))
from text_filter import clean_text  # noqa: E402

LABELS = ["negative", "neutral", "positive"]
TRAIN_FILE = ROOT / "data" / "training" / "train_set.csv"
OUT_DIR = ROOT / "data" / "models" / "berturk-sentiment"
BASE_MODEL = "dbmdz/bert-base-turkish-cased"
MAX_LENGTH = 128


def device(name="auto"):
    if name != "auto":
        return torch.device(name)
    if torch.backends.mps.is_available():
        return torch.device("mps")
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def load(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = [r for r in csv.DictReader(f)]
    labelled = [r for r in rows if r["label"] in LABELS]
    if len(labelled) < len(rows):
        print(f"note: {len(rows) - len(labelled)} rows without a valid label are skipped")
    if not labelled:
        sys.exit(f"No labelled rows in {path}")
    return [clean_text(r["text"]) for r in labelled], [LABELS.index(r["label"]) for r in labelled], labelled


def batches(texts, labels, size, rng=None):
    order = list(range(len(texts)))
    if rng:
        rng.shuffle(order)
    for i in range(0, len(order), size):
        idx = order[i:i + size]
        yield [texts[j] for j in idx], torch.tensor([labels[j] for j in idx])


def encode(tok, texts, dev):
    # fixed length: on Apple MPS every new tensor shape triggers a slow recompilation
    return tok(texts, return_tensors="pt", truncation=True, max_length=MAX_LENGTH, padding="max_length").to(dev)


def evaluate(model, tok, texts, labels, dev, batch_size):
    model.eval()
    preds = []
    with torch.no_grad():
        for bt, _ in batches(texts, labels, batch_size):
            enc = encode(tok, bt, dev)
            preds += model(**enc).logits.argmax(-1).cpu().tolist()
    return accuracy_score(labels, preds), f1_score(labels, preds, labels=[0, 1, 2], average="macro", zero_division=0)


def main(args):
    random.seed(args.seed)
    torch.manual_seed(args.seed)
    texts, labels, rows = load(args.train)
    tr_x, dv_x, tr_y, dv_y = train_test_split(texts, labels, test_size=0.1, stratify=labels, random_state=args.seed)
    counts = Counter(tr_y)
    dev = device(args.device)
    print(f"train {len(tr_x)} / dev {len(dv_x)} | classes: {dict((LABELS[k], v) for k, v in sorted(counts.items()))}"
          f" | labelers: {dict(Counter(r['labeler'] or '-' for r in rows))} | device: {dev}", flush=True)
    tok = AutoTokenizer.from_pretrained(args.base)
    model = AutoModelForSequenceClassification.from_pretrained(
        args.base, num_labels=3, id2label=dict(enumerate(LABELS)), label2id={l: i for i, l in enumerate(LABELS)},
        ignore_mismatched_sizes=True,          # a base with another classifier head gets a fresh 3-class head
    ).to(dev)

    weights = torch.tensor([len(tr_y) / (3 * counts[k]) for k in range(3)], dtype=torch.float).to(dev)
    loss_fn = torch.nn.CrossEntropyLoss(weight=weights)
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=0.01)
    steps = args.epochs * math.ceil(len(tr_x) / args.batch_size)
    warmup = int(0.1 * steps)
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt, lambda s: (s + 1) / warmup if s < warmup else max(0.0, (steps - s) / max(1, steps - warmup)))

    rng = random.Random(args.seed)
    best, history = -1.0, []
    per_epoch = math.ceil(len(tr_x) / args.batch_size)
    start = time.time()
    for epoch in range(1, args.epochs + 1):
        model.train()
        total = 0.0
        for step, (bt, by) in enumerate(batches(tr_x, tr_y, args.batch_size, rng), 1):
            enc = encode(tok, bt, dev)
            loss = loss_fn(model(**enc).logits, by.to(dev))
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            sched.step()
            opt.zero_grad()
            total += loss.item() * len(bt)
            if step == 1 or step % 10 == 0 or step == per_epoch:
                done = (epoch - 1) * per_epoch + step
                left = (time.time() - start) / done * (steps - done) / 60
                print(f"  epoch {epoch} step {step}/{per_epoch} | loss {loss.item():.3f} | "
                      f"~{left:.0f} min left", flush=True)
        acc, f1 = evaluate(model, tok, dv_x, dv_y, dev, args.batch_size)
        history.append({"epoch": epoch, "train_loss": round(total / len(tr_x), 4),
                        "dev_accuracy": round(acc, 4), "dev_macro_f1": round(f1, 4)})
        mark = ""
        if f1 > best:
            best, mark = f1, "  <- saved"
            args.out.mkdir(parents=True, exist_ok=True)
            model.save_pretrained(args.out)
            tok.save_pretrained(args.out)
        print(f"epoch {epoch}: loss {total / len(tr_x):.4f} | dev accuracy {acc:.3f} | dev macro-F1 {f1:.3f}{mark}")

    info = {"created_at": datetime.now().isoformat(timespec="seconds"), "base_model": args.base,
            "train_file": str(args.train.relative_to(ROOT) if args.train.is_relative_to(ROOT) else args.train),
            "train_rows": len(tr_x), "dev_rows": len(dv_x),
            "class_counts": {LABELS[k]: v for k, v in sorted(counts.items())},
            "labelers": dict(Counter(r["labeler"] or "-" for r in rows)),
            "epochs": args.epochs, "lr": args.lr, "batch_size": args.batch_size, "max_length": MAX_LENGTH,
            "seed": args.seed, "class_weights": [round(w, 3) for w in weights.tolist()],
            "best_dev_macro_f1": round(best, 4), "history": history}
    (args.out / "train_info.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nBest dev macro-F1 {best:.3f}; model: {args.out}")
    print("Next: python sentiment/evaluate_models.py --db data/work.db --files "
          "data/validation/validation_set.xlsx data/validation/validation_set_2.xlsx")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fine-tune BERTurk on the labelled training set.")
    parser.add_argument("--train", type=Path, default=TRAIN_FILE)
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    parser.add_argument("--base", default=BASE_MODEL)
    parser.add_argument("--epochs", type=int, default=4)
    parser.add_argument("--lr", type=float, default=2e-5)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--device", default="auto", help="auto (mps > cuda > cpu), mps, cuda or cpu")
    main(parser.parse_args())
