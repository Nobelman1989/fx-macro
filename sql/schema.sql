-- اسکیمای هسته پلتفرم تحلیل کلان فارکس
-- PostgreSQL 15+ بدون نیاز اجباری به TimescaleDB.
-- اگر افزونه موجود باشد، hypertable و فشرده‌سازی فعال می‌شود؛
-- اگر نباشد (Supabase/Railway/Neon)، جداول عادی ساخته می‌شوند — برای MVP کاملاً کافی.

DO $$ BEGIN
  CREATE EXTENSION IF NOT EXISTS timescaledb;
EXCEPTION WHEN OTHERS THEN
  RAISE NOTICE 'TimescaleDB in dastras nist — az jadval-haye standard Postgres estefade mishavad (baraye MVP kamel ast).';
END $$;

-- =====================================================
-- 1) تعریف شاخص‌های اقتصادی (متادیتا، تغییر نمی‌کند)
-- =====================================================
CREATE TABLE IF NOT EXISTS economic_events (
    event_code   TEXT PRIMARY KEY,
    country      CHAR(2) NOT NULL,
    currency     CHAR(3) NOT NULL,
    title        TEXT NOT NULL,
    importance   SMALLINT NOT NULL DEFAULT 1 CHECK (importance BETWEEN 1 AND 3),
    unit         TEXT,
    higher_is_hawkish BOOLEAN DEFAULT TRUE
);

-- =====================================================
-- 2) انتشارهای هر شاخص (سری زمانی اصلی)
-- =====================================================
CREATE TABLE IF NOT EXISTS releases (
    event_code        TEXT NOT NULL REFERENCES economic_events(event_code),
    release_time      TIMESTAMPTZ NOT NULL,
    previous          NUMERIC,
    forecast          NUMERIC,
    actual            NUMERIC,
    actual_recorded_at TIMESTAMPTZ,
    revised_from      NUMERIC,
    surprise          NUMERIC,
    surprise_z        NUMERIC,
    PRIMARY KEY (event_code, release_time)
);

DO $$ BEGIN
  PERFORM create_hypertable('releases', 'release_time', if_not_exists => TRUE);
EXCEPTION WHEN undefined_function THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS idx_releases_upcoming
    ON releases (release_time) WHERE actual IS NULL;

-- =====================================================
-- 3) قیمت OHLC یک‌دقیقه‌ای جفت‌ارزها
-- =====================================================
CREATE TABLE IF NOT EXISTS price_ohlc_1m (
    symbol  TEXT NOT NULL,
    ts      TIMESTAMPTZ NOT NULL,
    open    NUMERIC(12,6) NOT NULL,
    high    NUMERIC(12,6) NOT NULL,
    low     NUMERIC(12,6) NOT NULL,
    close   NUMERIC(12,6) NOT NULL,
    volume  NUMERIC,
    PRIMARY KEY (symbol, ts)
);

DO $$ BEGIN
  PERFORM create_hypertable('price_ohlc_1m', 'ts', if_not_exists => TRUE);
EXCEPTION WHEN undefined_function THEN NULL;
END $$;

DO $$ BEGIN
  ALTER TABLE price_ohlc_1m SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol'
  );
  PERFORM add_compression_policy('price_ohlc_1m', INTERVAL '30 days', if_not_exists => TRUE);
EXCEPTION WHEN OTHERS THEN NULL;
END $$;

-- =====================================================
-- 4) لاگ هشدارها
-- =====================================================
CREATE TABLE IF NOT EXISTS alerts_log (
    id           BIGSERIAL PRIMARY KEY,
    event_code   TEXT NOT NULL,
    release_time TIMESTAMPTZ NOT NULL,
    alert_type   TEXT NOT NULL,
    sent_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    payload      JSONB,
    UNIQUE (event_code, release_time, alert_type)
);

-- =====================================================
-- 5) بیانیه‌های بانک مرکزی (موتور لحن)
-- =====================================================
CREATE TABLE IF NOT EXISTS cb_statements (
    id            BIGSERIAL PRIMARY KEY,
    central_bank  TEXT NOT NULL,
    published_at  TIMESTAMPTZ NOT NULL,
    doc_type      TEXT NOT NULL,
    source_url    TEXT,
    raw_text      TEXT NOT NULL,
    tone_score    NUMERIC,
    tone_summary  TEXT,
    diff_vs_prev  TEXT
);

-- =====================================================
-- نمای کمکی: رویدادهای مهم ۴۸ ساعت آینده
-- =====================================================
CREATE OR REPLACE VIEW upcoming_high_impact AS
SELECT r.event_code, e.title, e.currency, e.importance,
       r.release_time, r.previous, r.forecast
FROM releases r
JOIN economic_events e USING (event_code)
WHERE r.actual IS NULL
  AND r.release_time BETWEEN now() AND now() + INTERVAL '48 hours'
  AND e.importance >= 2
ORDER BY r.release_time;
