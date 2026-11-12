-- =====================================================================
-- Borsa Analiz Sistemi - ortak veritabanı şeması (sürüm 2)
-- Kaynak: "Veritabanı Şeması Önerisi" belgesi + Ceren'in geri bildirimi
--
-- Kurallar:
--   * Semboller THYAO biçiminde (".IS" yalnızca stocks.yahoo_symbol'da)
--   * Tarih  : YYYY-MM-DD
--   * Zaman  : YYYY-MM-DDTHH:MM:SS+03:00
--   * Her bağlantıda: PRAGMA foreign_keys = ON;
-- =====================================================================

-- ---------------------------------------------------------------------
-- FİYAT TARAFI
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS stocks (
    symbol       TEXT PRIMARY KEY
                 CHECK (symbol = UPPER(symbol) AND symbol NOT LIKE '%.%'),
    name         TEXT,
    yahoo_symbol TEXT NOT NULL UNIQUE,
    kap_oid      TEXT,
    exchange     TEXT NOT NULL DEFAULT 'BIST',
    currency     TEXT NOT NULL DEFAULT 'TRY'
);

CREATE TABLE IF NOT EXISTS prices (
    symbol    TEXT    NOT NULL REFERENCES stocks(symbol),
    date      TEXT    NOT NULL
              CHECK (date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    open      REAL    NOT NULL CHECK (open > 0),
    high      REAL    NOT NULL CHECK (high > 0),
    low       REAL    NOT NULL CHECK (low > 0),
    close     REAL    NOT NULL CHECK (close > 0),
    adj_close REAL    NOT NULL CHECK (adj_close > 0),
    volume    INTEGER NOT NULL CHECK (volume >= 0),
    CHECK (low <= open AND open <= high AND low <= close AND close <= high),
    PRIMARY KEY (symbol, date)
);

-- İşlem günü takvimi: fiyatı olan günler (hafta sonu ve bayramlar yok)
CREATE VIEW IF NOT EXISTS trading_days AS
SELECT DISTINCT date FROM prices;

-- ---------------------------------------------------------------------
-- HABER VE DUYGU TARAFI
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS contents (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    type              TEXT NOT NULL CHECK (type IN ('news', 'kap', 'comment')),
    source            TEXT NOT NULL,
    title             TEXT,
    text              TEXT NOT NULL,
    url               TEXT,
    published_at      TEXT NOT NULL CHECK (published_at GLOB
        '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9][+-][0-9][0-9]:[0-9][0-9]'),
    trading_date      TEXT CHECK (trading_date IS NULL OR trading_date GLOB
        '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    purpose           TEXT NOT NULL DEFAULT 'analysis'
                      CHECK (purpose IN ('analysis', 'training')),
    source_id         TEXT,
    category          TEXT,
    is_company_notice INTEGER CHECK (is_company_notice IN (0, 1)),
    UNIQUE (source, source_id)
);

-- Bir içerik birden fazla hisseyle ilgili olabilir (çoka-çok ilişki)
CREATE TABLE IF NOT EXISTS content_symbols (
    content_id INTEGER NOT NULL REFERENCES contents(id) ON DELETE CASCADE,
    symbol     TEXT    NOT NULL REFERENCES stocks(symbol),
    PRIMARY KEY (content_id, symbol)
);

CREATE TABLE IF NOT EXISTS sentiments (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    content_id INTEGER NOT NULL REFERENCES contents(id) ON DELETE CASCADE,
    model      TEXT    NOT NULL,              -- 'BERTurk', 'TF-IDF+LR', 'manual'
    label      TEXT    NOT NULL
               CHECK (label IN ('positive', 'negative', 'neutral')),
    score      REAL    NOT NULL CHECK (score BETWEEN -1 AND 1),
    UNIQUE (content_id, model)
);

-- Sümeyye'nin modeline giden günlük özet (İG-14, İG-16).
-- BIST/MKK/Takasbank toplu duyuruları hariç tutulur.
CREATE VIEW IF NOT EXISTS daily_sentiment AS
SELECT
    cs.symbol,
    c.trading_date,
    s.model,
    AVG(CASE WHEN c.type IN ('news', 'kap') THEN s.score END)  AS news_avg_score,
    SUM(CASE WHEN c.type IN ('news', 'kap') THEN 1 ELSE 0 END) AS news_count,
    AVG(CASE WHEN c.type = 'comment' THEN s.score END)          AS comment_avg_score,
    SUM(CASE WHEN c.type = 'comment' THEN 1 ELSE 0 END)         AS comment_count
FROM sentiments s
JOIN contents c         ON c.id = s.content_id
JOIN content_symbols cs ON cs.content_id = c.id
WHERE c.purpose = 'analysis'
  AND c.trading_date IS NOT NULL
  AND (c.type <> 'kap' OR c.is_company_notice = 1)
GROUP BY cs.symbol, c.trading_date, s.model;

-- ---------------------------------------------------------------------
-- GÜNLÜK (İOG-G-04)
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS update_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    source     TEXT NOT NULL
               CHECK (source IN ('yfinance', 'kap', 'news', 'youtube', 'forum')),
    symbol     TEXT,
    run_at     TEXT NOT NULL,
    status     TEXT NOT NULL CHECK (status IN ('success', 'error')),
    input_rows INTEGER,
    removed    INTEGER,
    inserted   INTEGER,
    existing   INTEGER,
    detail     TEXT
);
