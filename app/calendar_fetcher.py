"""جمع‌آوری داده‌های اقتصادی از Alpha Vantage (رایگان) و upsert در دیتابیس.

Alpha Vantage برخلاف Finnhub تقویم آینده ندارد — سری زمانی تاریخی می‌دهد.
برای هر شاخص، جدیدترین مقدار را پیدا می‌کنیم؛ اگر در DB نبود یا تازه‌تر بود
به‌عنوان یک «انتشار» ثبت می‌کنیم.  forecast=NULL است چون AV آن را نمی‌دهد.
"""
import os
import logging
from datetime import datetime, timezone

import httpx

from db import db

log = logging.getLogger("calendar")

AV_KEY = os.environ.get("AV_API_KEY") or os.environ.get("FINNHUB_API_KEY", "demo")
AV_BASE = "https://www.alphavantage.co/query"

# نگاشت event_code → (AV function, interval)
AV_MAP: dict[str, tuple[str, str]] = {
    "US_NFP":          ("NONFARM_PAYROLL", "monthly"),
    "US_CPI_YOY":      ("CPI",             "monthly"),
    "US_GDP_QOQ_ADV":  ("REAL_GDP",        "quarterly"),
    "US_UNEMPLOYMENT": ("UNEMPLOYMENT",    "monthly"),
    "US_RETAIL_MOM":   ("RETAIL_SALES",    "monthly"),
}


def _fetch_av(function: str, interval: str | None = None) -> list[dict]:
    """یک تابع AV را می‌گیرد و سری زمانی را برمی‌گرداند."""
    params: dict = {"function": function, "apikey": AV_KEY}
    if interval:
        params["interval"] = interval
    r = httpx.get(AV_BASE, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()
    # پاسخ AV معمولاً {"data": [{"date":..., "value":...}, ...]}
    return data.get("data", [])


def fetch_window(days_back: int = 2, days_fwd: int = 14) -> list[dict]:
    """برای سازگاری با main.py همان امضا را نگه می‌داریم.
    به جای تقویم آینده، جدیدترین داده‌های موجود را برمی‌گردانیم."""
    rows: list[dict] = []
    for event_code, (av_func, interval) in AV_MAP.items():
        try:
            series = _fetch_av(av_func, interval)
            if not series:
                continue
            # اولین (جدیدترین) مقدار
            latest = series[0]
            previous = series[1] if len(series) > 1 else {}
            date_str = latest.get("date", "")
            if not date_str:
                continue
            # AV تاریخ می‌دهد نه timestamp؛ ساعت ۱۳:۳۰ UTC (زمان معمول اعلام آمریکایی)
            release_dt = datetime.fromisoformat(date_str + "T13:30:00").replace(
                tzinfo=timezone.utc
            )
            try:
                actual_val = float(latest["value"])
            except (KeyError, ValueError, TypeError):
                actual_val = None
            try:
                prev_val = float(previous.get("value", ""))
            except (ValueError, TypeError):
                prev_val = None

            rows.append({
                "_event_code": event_code,
                "time": release_dt.isoformat(),
                "actual": actual_val,
                "prev": prev_val,
                "estimate": None,   # AV اعداد پیش‌بینی ندارد
            })
            log.debug("%s → %s actual=%s", event_code, date_str, actual_val)
        except Exception as exc:
            log.warning("AV fetch failed for %s: %s", event_code, exc)
    return rows


def upsert(rows: list[dict]) -> list[tuple[str, datetime]]:
    """رویدادها را upsert می‌کند و لیست انتشارهایی که «تازه actual گرفتند»
    را برمی‌گرداند تا موتور سورپرایز فوراً روی آن‌ها اجرا شود."""
    fresh: list[tuple[str, datetime]] = []
    seen_at = datetime.now(timezone.utc)

    with db() as conn:
        for row in rows:
            code = row.get("_event_code")
            if not code:
                continue
            t = datetime.fromisoformat(row["time"])
            if t.tzinfo is None:
                t = t.replace(tzinfo=timezone.utc)
            cur = conn.execute(
                """
                INSERT INTO releases
                    (event_code, release_time, previous, forecast, actual,
                     actual_recorded_at)
                VALUES (%s, %s, %s, %s, %s,
                        CASE WHEN %s::numeric IS NOT NULL THEN %s END)
                ON CONFLICT (event_code, release_time) DO UPDATE SET
                    previous = COALESCE(EXCLUDED.previous, releases.previous),
                    forecast = COALESCE(EXCLUDED.forecast, releases.forecast),
                    actual   = COALESCE(EXCLUDED.actual,   releases.actual),
                    actual_recorded_at = CASE
                        WHEN releases.actual IS NULL
                         AND EXCLUDED.actual IS NOT NULL
                        THEN %s ELSE releases.actual_recorded_at END
                RETURNING (xmax <> 0 OR true),
                          (actual IS NOT NULL AND surprise_z IS NULL)
                """,
                (code, t, row.get("prev"), row.get("estimate"), row.get("actual"),
                 row.get("actual"), seen_at, seen_at),
            )
            _, just_got_actual = cur.fetchone()
            if just_got_actual:
                fresh.append((code, t))

    if fresh:
        log.info("actual تازه برای: %s", fresh)
    return fresh


def _next_release_date(event_code: str, last_date: datetime, interval: str) -> datetime:
    """تاریخ تقریبی انتشار بعدی را محاسبه می‌کند."""
    from calendar import monthrange

    if event_code in ("US_NFP", "US_UNEMPLOYMENT"):
        # NFP و بیکاری: اولین جمعه‌ی ماه بعد، ۱۳:۳۰ UTC
        year = last_date.year + (last_date.month // 12)
        month = (last_date.month % 12) + 1
        first = datetime(year, month, 1, 13, 30, tzinfo=timezone.utc)
        days_ahead = (4 - first.weekday()) % 7   # جمعه = weekday 4
        return first + timedelta(days=days_ahead)

    if interval == "quarterly":
        # GDP تقریباً ۹۰ روز بعد
        return last_date + timedelta(days=90)

    # ماهانه: تقریباً ۳۵ روز بعد (برای جلوگیری از افتادن در همان ماه)
    year = last_date.year + (last_date.month // 12)
    month = (last_date.month % 12) + 1
    day = min(last_date.day, monthrange(year, month)[1])
    return last_date.replace(year=year, month=month, day=day)


def schedule_upcoming() -> None:
    """برای هر شاخص، یک ردیف پیش‌بینی‌شده (actual=NULL) در releases می‌گذارد
    تا نمای تقویم آینده چیزی برای نمایش داشته باشد."""
    with db() as conn:
        for event_code, (_, interval) in AV_MAP.items():
            # آخرین actual را از DB می‌گیریم
            cur = conn.execute(
                """SELECT release_time, actual FROM releases
                   WHERE event_code = %s AND actual IS NOT NULL
                   ORDER BY release_time DESC LIMIT 1""",
                (event_code,),
            )
            row = cur.fetchone()
            if row is None:
                continue
            last_dt, last_actual = row
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)

            next_dt = _next_release_date(event_code, last_dt, interval)
            if next_dt <= datetime.now(timezone.utc):
                continue   # تاریخ گذشته است، رد کن

            # فقط اگر هنوز ثبت نشده
            conn.execute(
                """INSERT INTO releases (event_code, release_time, previous)
                   VALUES (%s, %s, %s)
                   ON CONFLICT (event_code, release_time) DO NOTHING""",
                (event_code, next_dt, last_actual),
            )
            log.debug("upcoming scheduled: %s @ %s", event_code, next_dt.date())


def polling_interval_seconds() -> int:
    """Alpha Vantage رایگان ۲۵ درخواست/روز دارد (AV_MAP داریم ۵ شاخص).
    هر ۲ ساعت یک‌بار کافی است — ۱۲ بار × ۵ شاخص = ۶۰ درخواست/روز
    اگر پلن رایگان standard (500/day) دارید همین کافی است."""
    return 7_200   # هر ۲ ساعت
