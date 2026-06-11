"""موتور واکنش تاریخی.

سؤالی که جواب می‌دهد:
«وقتی این شاخص سورپرایزی مشابه امروز داشت، جفت‌ارز X در
۱۵ دقیقه / ۱ ساعت / ۴ ساعت / ۲۴ ساعت بعد چه کرد؟»

خروجی توزیع کامل است (میانه + نرخ جهت)، نه فقط میانگین —
چون میانگین با یک outlier (مثلاً روز مداخله بانک مرکزی) خراب می‌شود.
"""
from datetime import datetime, timedelta
from statistics import median

from db import db

WINDOWS = {"15m": 15, "1h": 60, "4h": 240, "24h": 1440}

# اندازه پیپ برای هر جفت‌ارز (جفت‌های JPY متفاوت‌اند)
PIP = {"USDJPY": 0.01, "EURJPY": 0.01, "GBPJPY": 0.01}
DEFAULT_PIP = 0.0001


def _price_at(conn, symbol: str, t: datetime) -> float | None:
    """قیمت close نزدیک‌ترین کندل یک‌دقیقه‌ای در/بعد از لحظه t (تا ۵ دقیقه تلورانس)."""
    cur = conn.execute(
        """SELECT close FROM price_ohlc_1m
           WHERE symbol = %s AND ts >= %s AND ts < %s + INTERVAL '5 minutes'
           ORDER BY ts LIMIT 1""",
        (symbol, t, t),
    )
    row = cur.fetchone()
    return float(row[0]) if row else None


def reaction_profile(
    event_code: str,
    symbol: str,
    z_min: float | None = 1.0,
    z_max: float | None = None,
) -> dict:
    """پروفایل واکنش symbol به انتشارهای event_code در بازه سورپرایز داده‌شده.

    مثال: reaction_profile('US_CPI_YOY', 'EURUSD', z_min=1.0)
    → واکنش یورودلار به سورپرایزهای مثبت بزرگ CPI آمریکا.
    برای سورپرایز منفی: z_min=None, z_max=-1.0
    """
    pip = PIP.get(symbol, DEFAULT_PIP)
    conds, params = ["event_code = %s", "surprise_z IS NOT NULL"], [event_code]
    if z_min is not None:
        conds.append("surprise_z >= %s")
        params.append(z_min)
    if z_max is not None:
        conds.append("surprise_z <= %s")
        params.append(z_max)

    with db() as conn:
        cur = conn.execute(
            f"SELECT release_time, surprise_z FROM releases WHERE {' AND '.join(conds)}"
            " ORDER BY release_time",
            params,
        )
        episodes = cur.fetchall()

        moves: dict[str, list[float]] = {w: [] for w in WINDOWS}
        for release_time, _z in episodes:
            p0 = _price_at(conn, symbol, release_time)
            if p0 is None:
                continue
            for wname, minutes in WINDOWS.items():
                p1 = _price_at(conn, symbol, release_time + timedelta(minutes=minutes))
                if p1 is not None:
                    moves[wname].append((p1 - p0) / pip)

    out = {"event_code": event_code, "symbol": symbol, "episodes": len(episodes)}
    for wname, vals in moves.items():
        if not vals:
            out[wname] = None
            continue
        neg = sum(1 for v in vals if v < 0)
        out[wname] = {
            "n": len(vals),
            "median_pips": round(median(vals), 1),
            "down_rate": round(neg / len(vals), 2),   # سهم مواردی که قیمت ریخت
            "worst": round(min(vals), 1),
            "best": round(max(vals), 1),
        }
    return out
