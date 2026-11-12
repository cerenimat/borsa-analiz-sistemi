"""
Validation set for the sentiment models (H3 / İG-15)

Draws a reproducible random sample from the database and writes an Excel file
for manual labelling:

    batch 1 (natural distribution)
        news      100 items: 50 KAP company notices + 50 news headlines
        comments  100 YouTube comments
    batch 2 (only texts that enter the analysis, see text_filter.py; rows of
             batch 1 are never drawn again)
        news      100 items: 50 KAP special-situation notices (ODA) + 50 headlines
        comments  100 items: 50 YouTube + 50 Hisse.net forum posts

Each part is spread evenly over the years (2023-2026) so that every period is
represented. Only content used for analysis is sampled (purpose = 'analysis';
for KAP only the company's own notices, as in daily_sentiment). Texts that occur
more than once are sampled only once.

The labelled file is the ground truth for accuracy / F1 of every model, so it
must never be used for training.

Rows are identified by (source, source_id), not by contents.id: ids differ
between database copies, the pair is the same everywhere.

The database is opened read-only. Same --seed + same database = same sample.

Run (from the project root):
    python sentiment/make_validation_set.py --db data/work.db              # batch 1
    python sentiment/make_validation_set.py --db data/work.db --batch 2    # batch 2
Output:
    data/validation/validation_set.xlsx    (batch 1; sheets: news, comments, guide, info)
    data/validation/validation_set_2.xlsx  (batch 2)
"""
import argparse
import random
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "sentiment"))
from text_filter import exclusion  # noqa: E402

VALIDATION_DIR = ROOT / "data" / "validation"
OUT = {1: VALIDATION_DIR / "validation_set.xlsx", 2: VALIDATION_DIR / "validation_set_2.xlsx"}
LABELS = ("positive", "negative", "neutral")
YEARS = (2023, 2024, 2025, 2026)

# batch -> part name -> (SQL filter, size, sheet)
PARTS = {
    1: {
        "kap": ("c.type = 'kap' AND c.is_company_notice = 1", 50, "news"),
        "news": ("c.type = 'news'", 50, "news"),
        "comment": ("c.type = 'comment' AND length(trim(c.text)) >= 10", 100, "comments"),
    },
    2: {
        "kap": ("c.type = 'kap' AND c.is_company_notice = 1 AND c.category = 'ODA'", 50, "news"),
        "news": ("c.type = 'news'", 50, "news"),
        "youtube": ("c.type = 'comment' AND c.source = 'YouTube'", 50, "comments"),
        "forum": ("c.type = 'comment' AND c.source = 'Hisse.net'", 50, "comments"),
    },
}

QUERY = """
SELECT c.source, c.source_id, c.type, c.published_at, c.title, c.text, c.url,
       group_concat(cs.symbol, ', ') AS symbols, c.category, c.is_company_notice
FROM contents c JOIN content_symbols cs ON cs.content_id = c.id
WHERE c.purpose = 'analysis' AND {where} AND substr(c.published_at, 1, 4) = ?
GROUP BY c.id
ORDER BY c.source, c.source_id
"""

COLUMNS = ["source", "source_id", "type", "symbols", "published_at", "title", "text", "label", "note"]
WIDTHS = [18, 14, 9, 14, 20, 40, 80, 12, 30]

GUIDE = [
    ("Amaç", "Her satır için metnin, ilgili hisse (symbols sütunu) için yatırımcı açısından duygusunu seçin."),
    ("positive", "Hisse için iyi haber / iyimser beklenti: kâr artışı, yeni sipariş/ihale, hedef fiyat yükseltme, "
                 "temettü, 'yükselir', 'aldım, hedef 400' gibi."),
    ("negative", "Hisse için kötü haber / kötümser beklenti: zarar, ceza, dava, satış önerisi, düşüş beklentisi, "
                 "'zararım çıksa yeter', 'kaçın bu hisseden' gibi."),
    ("neutral", "Bilgi verici ya da yönsüz: genel kurul tarihi, sorumluluk beyanı, soru ('ne olur?'), "
                "hisseyle ilgisiz yorum ('emeğine sağlık', şaka), karışık/ikili duygu."),
    ("Kural 1", "Metni okuyup ilk izleniminize göre karar verin; modelin ne diyeceğini düşünmeyin."),
    ("Kural 2", "Başka bir hisseden bahsediyorsa, symbols sütunundaki hisse açısından değerlendirin; ilgisizse neutral."),
    ("Kural 3", "İroni/alay varsa kastedilen anlama göre etiketleyin (ör. 'harika, yine dibe vurdu' = negative)."),
    ("Kural 4", "Emin olmadığınız satırlara yine bir etiket verin ve note sütununa kısa not düşün."),
    ("Kural 5", "label sütununda yalnızca listedeki üç değer kullanılır: positive, negative, neutral."),
    ("Önemli", "Bu dosya modellerin doğruluk/F1 ölçümü için 'doğru cevap'tır; hiçbir modelin eğitiminde kullanılmaz."),
]


def text_key(text):
    return " ".join((text or "").split()).lower()


def sample_part(conn, where, size, rng, skip=frozenset(), filtered=False, skip_texts=frozenset()):
    """Evenly over YEARS; a year with too few rows passes its share to the others.
    `skip`: (source, source_id) keys already labelled; `filtered`: only texts that enter the analysis;
    `skip_texts`: normalised texts that must not be drawn (same text under another id)."""
    pools = {}
    for year in YEARS:
        rows, seen = [], set(skip_texts)
        for row in conn.execute(QUERY.format(where=where), (str(year),)):
            if (row[0], str(row[1])) in skip:
                continue
            if filtered and exclusion(row[2], row[8], row[9], row[5], row[0]):
                continue
            key = text_key(row[5])
            if key not in seen:                       # same text only once
                seen.add(key)
                rows.append(row)
        rng.shuffle(rows)
        pools[year] = rows
    picked = {y: [] for y in YEARS}
    remaining = size
    while remaining:
        open_years = [y for y in YEARS if len(picked[y]) < len(pools[y])]
        if not open_years:
            break
        share = max(1, remaining // len(open_years))
        for year in open_years:
            take = min(share, len(pools[year]) - len(picked[year]), remaining)
            picked[year] += pools[year][len(picked[year]):len(picked[year]) + take]
            remaining -= take
            if not remaining:
                break
    rows = [r for y in YEARS for r in picked[y]]
    rng.shuffle(rows)                                  # labeller does not see year blocks
    return rows, {y: len(picked[y]) for y in YEARS}


def write_sheet(ws, rows):
    ws.append(COLUMNS)
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="DDDDDD")
    for source, source_id, ctype, published, title, text, _url, symbols, *_ in rows:
        ws.append([source, source_id, ctype, symbols, published, title, text, None, None])
    for i, width in enumerate(WIDTHS):
        ws.column_dimensions[chr(65 + i)].width = width
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "A2"
    dv = DataValidation(type="list", formula1=f'"{",".join(LABELS)}"', allow_blank=True,
                        showErrorMessage=True, errorTitle="Geçersiz etiket",
                        error="Yalnızca positive, negative veya neutral")
    ws.add_data_validation(dv)
    dv.add(f"H2:H{len(rows) + 1}")


def labelled_keys(paths, with_texts=False):
    """(source, source_id) of every row in earlier validation files (and their normalised texts)."""
    keys, texts = set(), set()
    for path in paths:
        wb = load_workbook(path, read_only=True)
        for sheet in ("news", "comments"):
            for row in wb[sheet].iter_rows(min_row=2, values_only=True):
                keys.add((row[0], str(row[1])))
                texts.add(text_key(row[6]))
    return (keys, texts) if with_texts else keys


def main(db_path, out, seed, batch=1, exclude=()):
    if not db_path.exists():
        sys.exit(f"Database not found: {db_path}")
    if out.exists():
        sys.exit(f"{out} already exists; it may hold labels. Move or rename it first.")
    skip = labelled_keys(exclude)
    rng = random.Random(seed)
    conn = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
    parts, counts = {}, {}
    for name, (where, size, _sheet) in PARTS[batch].items():
        parts[name], counts[name] = sample_part(conn, where, size, rng, skip, filtered=batch > 1)
    conn.close()

    wb = Workbook()
    sheets = {}
    for name, (_where, _size, sheet) in PARTS[batch].items():
        sheets.setdefault(sheet, []).extend(parts[name])
    news = wb.active
    news.title = "news"
    news_rows = sheets["news"]
    rng.shuffle(news_rows)
    write_sheet(news, news_rows)
    comment_rows = sheets["comments"]
    if batch > 1:
        rng.shuffle(comment_rows)                      # mix YouTube and forum posts
    write_sheet(wb.create_sheet("comments"), comment_rows)

    guide = wb.create_sheet("guide")
    for key, value in GUIDE:
        guide.append([key, value])
    guide.column_dimensions["A"].width = 12
    guide.column_dimensions["B"].width = 120
    for row in guide.iter_rows():
        row[0].font = Font(bold=True)
        row[1].alignment = Alignment(wrap_text=True, vertical="top")

    info = wb.create_sheet("info")
    for item in [("created_at", datetime.now().isoformat(timespec="seconds")),
                 ("database", db_path.name), ("seed", seed), ("batch", batch),
                 ("excluded_rows_from", ", ".join(p.name for p in exclude) or "-"),
                 ("filter", "text_filter.exclusion" if batch > 1 else "-"),
                 *[(f"{name}_per_year", str(c)) for name, c in counts.items()]]:
        info.append(list(item))

    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    for name, c in counts.items():
        print(f"{name:<8} {sum(c.values()):>3}  {c}")
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create the manual labelling file (validation set).")
    parser.add_argument("--db", type=Path, required=True, help="database with KAP, news and comments")
    parser.add_argument("--batch", type=int, choices=(1, 2), default=1, help="1: natural sample, 2: filtered")
    parser.add_argument("--out", type=Path, help="output .xlsx (default depends on --batch)")
    parser.add_argument("--exclude", type=Path, nargs="*",
                        help="earlier validation files whose rows are not drawn again "
                             "(default for batch 2: validation_set.xlsx)")
    parser.add_argument("--seed", type=int, default=42, help="random seed (keep 42 for the report)")
    args = parser.parse_args()
    exclude = args.exclude if args.exclude is not None else ([OUT[1]] if args.batch > 1 else [])
    main(args.db, args.out or OUT[args.batch], args.seed, args.batch, exclude)
