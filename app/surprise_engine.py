"""موتور Surprise Index — قلب پلتفرم.

فرمول:  surprise_z = (actual − forecast) / σ
که σ انحراف معیارِ سورپرایزهای تاریخی همان شاخص است (آخرین N انتشار).

چرا نرمال‌سازی؟ سورپرایز ۰.۱٪ در CPI بزرگ است، ولی ۲۰K در NFP هیچ.
با z-score هر دو روی یک مقیاس قابل مقایسه می‌شوند و آستانه هشدار
برای همه شاخص‌ها یکسان تعریف می‌شود.
"""
import logging
from datetime import datetime
from statistics import stdev

from db import db

log = logging.getLogger("surprise")

HISTORY_N = 24          # تعداد انتشارهای گذشته برای محاسبه سیگما (~۲ سال داده ماهانه)
MIN_HISTORY = 8         # کمتر از این، z گزارش نمی‌شود (سیگما ناپایدار است)
ALERT_THRESHOLD_Z = 1.0 # قدر مطلق z بالاتر از این → هشدار فوری


def compute_surprise(event_code: str, release_time: datetime) -> dict | None:
    """سورپرایز یک انتشار مشخص را محاسبه و در DB ذخیره می‌کند."""
    with db() as conn:
        cur = conn.execute(
            """SELECT actual, forecast FROM releases
               WHERE event_code = %s AND release_time = %s""",
            (event_code, release_time),
        )
        row = cur.fetchone()
        if row is None or row[0] is None or row[1] is None:
            return None
        actual, forecast = float(row[0]), float(row[1])
        surprise = actual - forecast

        cur = conn.execute(
            """SELECT actual - forecast FROM releases
               WHERE event_code = %s AND release_time < %s
                 AND actual IS NOT NULL AND forecast IS NOT NULL
               ORDER BY release_time DESC LIMIT %s""",
            (event_code, release_time, HISTORY_N),
        )
        hist = [float(r[0]) for r in cur.fetchall()]

        z = None
        if len(hist) >= MIN_HISTORY:
            sigma = stdev(hist)
            if sigma > 0:
                z = surprise / sigma

        conn.execute(
            """UPDATE releases SET surprise = %s, surprise_z = %s
               WHERE event_code = %s AND release_time = %s""",
            (surprise, z, event_code, release_time),
        )

    result = {
        "event_code": event_code,
        "release_time": release_time,
        "actual": actual,
        "forecast": forecast,
        "surprise": surprise,
        "surprise_z": z,
        "history_n": len(hist),
        "alert": z is not None and abs(z) >= ALERT_THRESHOLD_Z,
    }
    log.info("surprise %s @ %s → z=%s", event_code, release_time, z)
    return result


def feed_latency_report() -> list[tuple]:
    """گزارش تأخیر فید — اگر میانه بالای چند ثانیه بود، منبع داده را عوض کن."""
    with db() as conn:
        cur = conn.execute(
            """SELECT event_code,
                      percentile_cont(0.5) WITHIN GROUP
                        (ORDER BY EXTRACT(EPOCH FROM (actual_recorded_at - release_time)))
                        AS median_latency_sec,
                      COUNT(*)
               FROM releases
               WHERE actual_recorded_at IS NOT NULL
               GROUP BY event_code ORDER BY 2 DESC"""
        )
        return cur.fetchall()
