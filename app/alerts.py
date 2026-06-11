"""هشدار تلگرام — سریع‌ترین مسیر رساندن سیگنال به کاربر در MVP.

دو نوع هشدار:
  pre_event       → ۳۰ دقیقه قبل از رویداد مهم (با Forecast/Previous)
  actual_released → لحظه انتشار، با Surprise Index و پروفایل تاریخی
"""
import json
import logging
import os

import httpx

from db import db

log = logging.getLogger("alerts")

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
API = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"


def _send(text: str) -> None:
    httpx.post(API, json={"chat_id": CHAT_ID, "text": text,
                          "parse_mode": "HTML"}, timeout=10)


def _already_sent(conn, event_code, release_time, alert_type) -> bool:
    cur = conn.execute(
        """INSERT INTO alerts_log (event_code, release_time, alert_type, payload)
           VALUES (%s, %s, %s, %s)
           ON CONFLICT DO NOTHING RETURNING id""",
        (event_code, release_time, alert_type, json.dumps({})),
    )
    return cur.fetchone() is None   # اگر insert نشد یعنی قبلاً ارسال شده


def send_pre_event_alerts() -> None:
    """رویدادهای مهمِ ۳۰ دقیقه آینده."""
    with db() as conn:
        cur = conn.execute(
            """SELECT event_code, title, currency, release_time, previous, forecast
               FROM upcoming_high_impact
               WHERE release_time < now() + INTERVAL '30 minutes'"""
        )
        for code, title, ccy, t, prev, fc in cur.fetchall():
            if _already_sent(conn, code, t, "pre_event"):
                continue
            _send(
                f"⏰ <b>{title}</b> ({ccy})\n"
                f"زمان: {t:%H:%M UTC}\n"
                f"قبلی: {prev} | پیش‌بینی: {fc}\n"
                f"اسپرد در لحظه انتشار باز می‌شود — مدیریت پوزیشن یادت نرود."
            )
            log.info("pre-event alert sent: %s", code)


def send_surprise_alert(result: dict, reaction: dict | None = None) -> None:
    """بلافاصله بعد از محاسبه سورپرایز فراخوانی می‌شود."""
    code, t = result["event_code"], result["release_time"]
    with db() as conn:
        if _already_sent(conn, code, t, "actual_released"):
            return

    z = result["surprise_z"]
    direction = "🔴" if (z or 0) > 0.5 else ("🟢" if (z or 0) < -0.5 else "⚪")
    lines = [
        f"{direction} <b>{code}</b> منتشر شد",
        f"واقعی: {result['actual']} | پیش‌بینی: {result['forecast']}",
        f"Surprise Index: <b>{z:+.2f}σ</b>" if z is not None
        else "(تاریخچه برای z کافی نیست)",
    ]
    if reaction and reaction.get("15m"):
        r = reaction["15m"]
        lines.append(
            f"تاریخچه ({reaction['symbol']}): در {r['n']} مورد مشابه، "
            f"میانه حرکت ۱۵دقیقه {r['median_pips']:+.0f} پیپ، "
            f"{int(r['down_rate']*100)}٪ موارد نزولی"
        )
    _send("\n".join(lines))
    log.info("surprise alert sent: %s z=%s", code, z)
