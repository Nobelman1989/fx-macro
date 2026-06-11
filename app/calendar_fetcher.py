"""جمع‌آوری تقویم اقتصادی از Finnhub و upsert در دیتابیس.

نکته حیاتی: ستون actual_recorded_at لحظه دیدنِ عدد توسط ماست.
اختلاف آن با release_time = تأخیر فید. اگر این تأخیر بالای ~۵ ثانیه باشد،
باید منبع داده را عوض کنی، چون Surprise Index لحظه‌ای بی‌ارزش می‌شود.
"""
import os
import logging
from datetime import datetime, timedelta, timezone

import httpx

from db import db

log = logging.getLogger("calendar")

FINNHUB_KEY = os.environ["FINNHUB_API_KEY"]
CALENDAR_URL = "https://finnhub.io/api/v1/calendar/economic"

# نگاشت رویدادهای Finnhub به event_code داخلی ما.
# فقط رویدادهایی که اینجا تعریف شده‌اند وارد سیستم می‌شوند (فیلتر نویز).
EVENT_MAP = {
    ("US", "CPI YoY"):                    "US_CPI_YOY",
    ("US", "Core CPI YoY"):               "US_CORE_CPI_YOY",
    ("US", "Nonfarm Payrolls"):           "US_NFP",
    ("US", "Unemployment Rate"):          "US_UNEMPLOYMENT",
    ("US", "Average Hourly Earnings MoM"): "US_AHE_MOM",
    ("US", "GDP Growth Rate QoQ Adv"):    "US_GDP_QOQ_ADV",
    ("US", "Core PCE Price Index YoY"):   "US_CORE_PCE_YOY",
    ("US", "Initial Jobless Claims"):     "US_JOBLESS_CLAIMS",
    ("US", "Retail Sales MoM"):           "US_RETAIL_MOM",
    ("US", "ISM Manufacturing PMI"):      "US_ISM_MFG",
    ("EU", "Inflation Rate YoY Flash"):   "EU_CPI_FLASH_YOY",
    ("GB", "Inflation Rate YoY"):         "GB_CPI_YOY",
}


def fetch_window(days_back: int = 2, days_fwd: int = 14) -> list[dict]:
    """بازه‌ای از تقویم را می‌گیرد: گذشته نزدیک (برای گرفتن actual) + آینده."""
    now = datetime.now(timezone.utc)
    params = {
        "from": (now - timedelta(days=days_back)).strftime("%Y-%m-%d"),
        "to": (now + timedelta(days=days_fwd)).strftime("%Y-%m-%d"),
        "token": FINNHUB_KEY,
    }
    r = httpx.get(CALENDAR_URL, params=params, timeout=15)
    r.raise_for_status()
    return r.json().get("economicCalendar", [])


def upsert(rows: list[dict]) -> list[tuple[str, datetime]]:
    """رویدادها را upsert می‌کند و لیست انتشارهایی که «تازه actual گرفتند»
    را برمی‌گرداند تا موتور سورپرایز فوراً روی آن‌ها اجرا شود."""
    fresh: list[tuple[str, datetime]] = []
    seen_at = datetime.now(timezone.utc)

    with db() as conn:
        for row in rows:
            code = EVENT_MAP.get((row.get("country"), row.get("event")))
            if code is None:
                continue
            t = datetime.fromisoformat(row["time"].replace(" ", "T")).replace(
                tzinfo=timezone.utc
            )
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


def polling_interval_seconds() -> int:
    """polling تطبیقی: نزدیک رویداد مهم، سرعت بالا می‌رود."""
    with db() as conn:
        cur = conn.execute(
            """SELECT MIN(release_time) FROM upcoming_high_impact
               WHERE release_time < now() + INTERVAL '10 minutes'"""
        )
        soon = cur.fetchone()[0]
    if soon is not None:
        return 2      # پنجره داغ: هر ۲ ثانیه
    return 60         # حالت عادی: هر دقیقه
