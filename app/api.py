"""لایه‌ی وب FastAPI روی موتور fx-macro (فاز بعدی #۱).

همه‌ی توابع تحلیل را به‌صورت read-only از طریق HTTP در دسترس می‌گذارد تا
داشبورد (فاز ۳) یا هر کلاینت دیگری بتواند آن‌ها را مصرف کند. این سرویس
هیچ داده‌ای نمی‌نویسد؛ نوشتن داده کار حلقه‌ی main.py است.

اجرا:
    cd app && uvicorn api:app --reload --port 8000
    # سپس مستندات تعاملی: http://localhost:8000/docs

متغیرهای محیطی: همان‌های main.py (برای این سرویس حداقل FX_DB_DSN لازم است).
"""
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse

from cb_tone import history as cb_history
from cb_tone import latest as cb_latest
from db import db
from reaction_analyzer import reaction_profile
from surprise_engine import feed_latency_report

app = FastAPI(
    title="fx-macro API",
    version="0.1.0",
    description="Surprise Index + تحلیل واکنش تاریخی فارکس",
)

STATIC_DIR = Path(__file__).resolve().parent / "static"


@app.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    """داشبورد تک‌صفحه‌ای (HTML) که همین API را مصرف می‌کند — فاز بعدی #۳."""
    return FileResponse(STATIC_DIR / "dashboard.html")


def _rows_as_dicts(cur) -> list[dict]:
    """نتیجه‌ی یک cursor را به لیست دیکشنری تبدیل می‌کند (ستون‌ها از description)."""
    cols = [c.name for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


@app.get("/health")
def health() -> dict:
    """سلامت سرویس و اتصال دیتابیس."""
    try:
        with db() as conn:
            conn.execute("SELECT 1")
        return {"status": "ok", "db": "up"}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"db down: {e}")


@app.get("/events")
def events() -> list[dict]:
    """کاتالوگ شاخص‌های اقتصادی تعریف‌شده (متادیتا)."""
    with db() as conn:
        cur = conn.execute(
            """SELECT event_code, country, currency, title, importance, unit,
                      higher_is_hawkish
               FROM economic_events
               ORDER BY importance DESC, event_code"""
        )
        return _rows_as_dicts(cur)


@app.get("/calendar/upcoming")
def calendar_upcoming(days: int = Query(30, ge=1, le=90)) -> list[dict]:
    """رویدادهای پیشِ‌رو — پیش‌فرض ۳۰ روز آینده، اهمیت ۲+."""
    with db() as conn:
        cur = conn.execute(
            """SELECT r.event_code, e.title, e.currency, e.importance,
                      r.release_time, r.previous, r.forecast
               FROM releases r
               JOIN economic_events e USING (event_code)
               WHERE r.actual IS NULL
                 AND r.release_time BETWEEN now() AND now() + (%s || ' days')::INTERVAL
                 AND e.importance >= 2
               ORDER BY r.release_time""",
            (days,),
        )
        return _rows_as_dicts(cur)


@app.get("/releases/recent")
def releases_recent(
    event_code: Optional[str] = Query(None, description="فیلتر بر اساس کد شاخص"),
    limit: int = Query(50, ge=1, le=500),
) -> list[dict]:
    """آخرین انتشارهای دارای actual، همراه با Surprise Index محاسبه‌شده."""
    conds = ["actual IS NOT NULL"]
    params: list = []
    if event_code:
        conds.append("event_code = %s")
        params.append(event_code)
    params.append(limit)
    with db() as conn:
        cur = conn.execute(
            f"""SELECT event_code, release_time, previous, forecast, actual,
                       surprise, surprise_z, actual_recorded_at
                FROM releases
                WHERE {' AND '.join(conds)}
                ORDER BY release_time DESC
                LIMIT %s""",
            params,
        )
        return _rows_as_dicts(cur)


@app.get("/reaction/{event_code}")
def reaction(
    event_code: str,
    symbol: str = Query("EURUSD", description="جفت‌ارز، مثل EURUSD یا USDJPY"),
    direction: str = Query("positive", description="positive | negative"),
    threshold: float = Query(1.0, ge=0.0, description="آستانه‌ی |z| برای انتخاب اپیزودها"),
) -> dict:
    """پروفایل واکنش تاریخی قیمت به سورپرایزهای این شاخص.

    direction=positive → سورپرایزهای مثبت بزرگ (z >= threshold)
    direction=negative → سورپرایزهای منفی بزرگ (z <= -threshold)
    """
    if direction not in ("positive", "negative"):
        raise HTTPException(status_code=400, detail="direction باید positive یا negative باشد")
    if direction == "positive":
        return reaction_profile(event_code, symbol, z_min=threshold, z_max=None)
    return reaction_profile(event_code, symbol, z_min=None, z_max=-threshold)


@app.get("/feed-latency")
def feed_latency() -> list[dict]:
    """گزارش تأخیر فید برای هر شاخص (میانه‌ی ثانیه). اگر بالا بود، منبع داده را عوض کن."""
    rows = feed_latency_report()
    return [
        {
            "event_code": r[0],
            "median_latency_sec": float(r[1]) if r[1] is not None else None,
            "samples": r[2],
        }
        for r in rows
    ]


@app.get("/cb/latest")
def cb_latest_endpoint(
    central_bank: str = Query("FED", description="بانک مرکزی، مثل FED یا ECB"),
) -> dict:
    """آخرین بیانیه‌ی تحلیل‌شده‌ی یک بانک مرکزی (tone_score و خلاصه‌ی لحن)."""
    res = cb_latest(central_bank)
    if res is None:
        raise HTTPException(
            status_code=404, detail=f"بیانیه‌ای برای {central_bank.upper()} ثبت نشده"
        )
    return res


@app.get("/cb/history")
def cb_history_endpoint(
    central_bank: str = Query("FED", description="بانک مرکزی، مثل FED یا ECB"),
    limit: int = Query(20, ge=1, le=200),
) -> list[dict]:
    """تاریخچه‌ی لحن یک بانک مرکزی (برای رسم روند هاوکیش/داویش)."""
    return cb_history(central_bank, limit)
