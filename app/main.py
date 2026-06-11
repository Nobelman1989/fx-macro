"""حلقه اصلی پلتفرم — MVP بدون نیاز به Celery.

چرخه:
  1. تقویم را poll کن (تطبیقی: ۶۰ ثانیه عادی، ۲ ثانیه در پنجره داغ)
  2. هشدار pre-event برای رویدادهای ۳۰ دقیقه آینده
  3. اگر actual تازه‌ای رسید → Surprise Index → پروفایل تاریخی → هشدار فوری

اجرا:  python main.py
متغیرهای محیطی لازم: FX_DB_DSN, FINNHUB_API_KEY,
                      TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
"""
import logging
import time

import calendar_fetcher as cal
import alerts
from surprise_engine import compute_surprise
from reaction_analyzer import reaction_profile

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
log = logging.getLogger("main")

# برای هر شاخص، جفت‌ارزی که پروفایل تاریخی‌اش در هشدار می‌آید
PRIMARY_PAIR = {
    "US_CPI_YOY": "EURUSD", "US_CORE_CPI_YOY": "EURUSD",
    "US_NFP": "EURUSD", "US_CORE_PCE_YOY": "EURUSD",
    "US_GDP_QOQ_ADV": "EURUSD", "US_RETAIL_MOM": "EURUSD",
    "US_ISM_MFG": "EURUSD", "US_JOBLESS_CLAIMS": "USDJPY",
    "EU_CPI_FLASH_YOY": "EURUSD", "GB_CPI_YOY": "GBPUSD",
}


def tick() -> None:
    rows = cal.fetch_window()
    fresh = cal.upsert(rows)

    alerts.send_pre_event_alerts()

    for event_code, release_time in fresh:
        result = compute_surprise(event_code, release_time)
        if result is None:
            continue
        reaction = None
        z = result["surprise_z"]
        if z is not None and abs(z) >= 1.0:
            pair = PRIMARY_PAIR.get(event_code, "EURUSD")
            # پروفایل را در همان جهتِ سورپرایز امروز بساز
            if z > 0:
                reaction = reaction_profile(event_code, pair, z_min=1.0)
            else:
                reaction = reaction_profile(event_code, pair,
                                            z_min=None, z_max=-1.0)
        alerts.send_surprise_alert(result, reaction)


def main() -> None:
    log.info("fx-macro engine started")
    while True:
        try:
            tick()
        except Exception:
            log.exception("tick failed — retrying")
        time.sleep(cal.polling_interval_seconds())


if __name__ == "__main__":
    main()
