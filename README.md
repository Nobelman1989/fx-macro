# fx-macro — هسته MVP پلتفرم تحلیل کلان فارکس

موتور Surprise Index + تحلیل واکنش تاریخی + هشدار تلگرام.

## ساختار

```
fx-macro/
├── Dockerfile             ← کانتینر production (FastAPI + داشبورد)
├── Procfile               ← اجرای web برای Railway/Render
├── fly.toml               ← کانفیگ نمونه‌ی Fly.io
├── sql/
│   ├── schema.sql          ← اسکیمای TimescaleDB
│   └── seed_events.sql     ← تعریف ۱۲ شاخص اولیه
└── app/
    ├── db.py               ← pool اتصال
    ├── calendar_fetcher.py ← تقویم اقتصادی (Finnhub) + polling تطبیقی
    ├── surprise_engine.py  ← محاسبه z-score سورپرایز + پایش تأخیر فید
    ├── reaction_analyzer.py← پروفایل واکنش تاریخی قیمت
    ├── alerts.py           ← هشدار تلگرام (pre-event و لحظه انتشار)
    ├── load_history.py     ← ورود داده تاریخی CSV (Dukascopy)
    ├── main.py             ← حلقه اصلی (poll → surprise → alert)
    ├── cb_tone.py          ← موتور لحن بانک مرکزی (Fed/ECB) با LLM
    ├── api.py              ← لایه وب FastAPI (read-only روی همان توابع)
    └── static/
        └── dashboard.html ← داشبورد تک‌صفحه‌ای (همین API را مصرف می‌کند)
```

## راه‌اندازی (حدود ۳۰ دقیقه)

۱. دیتابیس:
```bash
docker run -d --name fxdb -p 5432:5432 \
  -e POSTGRES_USER=fx -e POSTGRES_PASSWORD=fx -e POSTGRES_DB=fxmacro \
  timescale/timescaledb:latest-pg16
psql postgresql://fx:fx@localhost:5432/fxmacro -f sql/schema.sql
psql postgresql://fx:fx@localhost:5432/fxmacro -f sql/seed_events.sql
```

۲. وابستگی‌ها:
```bash
pip install -r requirements.txt
```

۳. متغیرهای محیطی:
```bash
export FX_DB_DSN="postgresql://fx:fx@localhost:5432/fxmacro"
export FINNHUB_API_KEY="..."        # ثبت‌نام رایگان در finnhub.io
export TELEGRAM_BOT_TOKEN="..."     # از BotFather
export TELEGRAM_CHAT_ID="..."
export ANTHROPIC_API_KEY="..."      # برای موتور لحن بانک مرکزی (cb_tone.py)
```

۴. داده تاریخی (برای موتور واکنش):
```bash
# دانلود کندل ۱ دقیقه‌ای EURUSD از Dukascopy، سپس:
python app/load_history.py EURUSD eurusd_1m.csv
```

۵. اجرا:
```bash
cd app && python main.py        # حلقه اصلی: poll تقویم، محاسبه سورپرایز، هشدار تلگرام
```

## API وب (FastAPI)

موتور به‌صورت read-only از طریق HTTP هم در دسترس است (برای داشبورد یا هر کلاینت):

```bash
cd app && uvicorn api:app --reload --port 8000
# داشبورد:           http://localhost:8000/
# مستندات تعاملی:    http://localhost:8000/docs
```

اندپوینت‌ها:

| متد و مسیر | کار |
|---|---|
| `GET /health` | سلامت سرویس + اتصال دیتابیس |
| `GET /events` | کاتالوگ شاخص‌های تعریف‌شده |
| `GET /calendar/upcoming` | رویدادهای مهمِ ۴۸ ساعت آینده |
| `GET /releases/recent?event_code=&limit=` | آخرین انتشارها + Surprise Index |
| `GET /reaction/{event_code}?symbol=EURUSD&direction=positive\|negative&threshold=1.0` | پروفایل واکنش تاریخی قیمت |
| `GET /feed-latency` | میانه تأخیر فید برای هر شاخص |
| `GET /cb/latest?central_bank=FED` | آخرین لحن تحلیل‌شده‌ی بانک مرکزی (Fed/ECB) |
| `GET /cb/history?central_bank=FED&limit=20` | روند تاریخی لحن هاوکیش/داویش |

> این لایه فقط می‌خواند؛ نوشتن و poll کردن همچنان کار `main.py` است. برای داده‌ی واقعی، اول `main.py` را اجرا کن تا جدول‌ها پر شوند.

## داشبورد

با بالا آمدن همان سرویس FastAPI، یک داشبورد تک‌صفحه‌ای روی `http://localhost:8000/`
سرو می‌شود (`app/static/dashboard.html`). هیچ مرحله‌ی build یا Node لازم نیست —
چون هم‌origin با API است، مستقیم اندپوینت‌ها را با `fetch` می‌خواند و هر ۶۰ ثانیه
خودش را تازه می‌کند. کارت‌ها: تقویم ۴۸ ساعت آینده، آخرین انتشارها + Surprise Index،
گِیج لحن هاوکیش/داویش Fed و ECB، تأخیر فید، و کاتالوگ شاخص‌ها.

## موتور لحن بانک مرکزی (cb_tone.py)

بیانیه‌ی سیاست پولی Fed/ECB را می‌گیرد، با LLM لحن آن را از منظر
هاوکیش/داویش می‌سنجد (`tone_score` بین ‎-1.0‎ داویش تا ‎+1.0‎ هاوکیش)،
نسبت به بیانیه‌ی قبلی diff می‌گیرد، و در جدول `cb_statements` ذخیره می‌کند.

ورود داده عمداً در API نیست (API فقط read است). از CLI صدایش بزن — معمولاً
لینک آخرین بیانیه را از صفحه‌ی فهرست بانک مرکزی بردار و مستقیم بده:

```bash
export ANTHROPIC_API_KEY="..."
cd app && python cb_tone.py FED https://www.federalreserve.gov/.../monetary20260611a.htm
python cb_tone.py ECB <url>
```

سپس نتیجه از طریق API خوانده می‌شود: `GET /cb/latest?central_bank=FED` و
`GET /cb/history?central_bank=FED`. برای اجرای زمان‌بندی‌شده، همین دستور CLI
را در cron یا حلقه‌ی روزانه بگذار.

## استقرار روی اینترنت (تا داشبورد Forex Me زنده هم کار کند)

صفحه‌ی `/macro` در Forex Me از طریق پراکسی سمت‌سرور به این API وصل می‌شود؛
پس کافی است این سرویس یک **URL عمومی** داشته باشد و آن را در Vercel ست کنی.
کانتینر آماده است (`Dockerfile`, `Procfile`, `fly.toml`).

**۱) دیتابیس (نیازمند TimescaleDB).** ساده‌ترین راه، یک دیتابیس رایگان روی
[Timescale Cloud](https://www.timescale.com/cloud) بساز (افزونه از قبل نصب است)،
سپس اسکیمای پروژه را اجرا کن:
```bash
psql "$FX_DB_DSN" -f sql/schema.sql
psql "$FX_DB_DSN" -f sql/seed_events.sql
```

**۲) سرویس API.** با هر پلتفرمی که Dockerfile یا Procfile را می‌فهمد دیپلوی کن.
نمونه با Fly.io:
```bash
fly launch --no-deploy          # نام و منطقه را تأیید کن (از fly.toml می‌خواند)
fly secrets set \
  FX_DB_DSN="postgresql://..." \
  ANTHROPIC_API_KEY="..." \
  FINNHUB_API_KEY="..." \
  TELEGRAM_BOT_TOKEN="..." TELEGRAM_CHAT_ID="..."
fly deploy
# → یک URL عمومی می‌دهد، مثل https://fx-macro.fly.dev
```
(Railway/Render هم با همین Dockerfile کار می‌کنند؛ فقط همان متغیرها را به‌عنوان
env بده. سلامت سرویس روی `/health` چک می‌شود.)

> امنیت: مرورگرِ کاربر مستقیماً به این سرویس وصل نمی‌شود — پراکسی Vercel سمت‌سرور
> صدایش می‌زند، پس CORS لازم نیست. سرویس فقط می‌خواند و کلیدها فقط در secrets
> پلتفرم می‌مانند (نه در کد).

**۳) اتصال به سایت زنده.** URL بالا را در Vercelِ Forex Me ست کن و ری‌دیپلوی:
```bash
vercel env add FX_MACRO_API_BASE production   # سپس URL را پیست کن
vercel --prod                                  # یا یک push به main
```
از این لحظه صفحه‌ی `/macro` روی دامنه‌ی زنده هم پر می‌شود (تا داده باشد).
بدون این مرحله، سایت زنده پیام «سرویس در دسترس نیست» نشان می‌دهد و بقیه‌ی اپ سالم است.

> هشدار هزینه/داده: برای داده‌ی واقعی باید `main.py` هم جایی به‌صورت دائمی اجرا شود
> (worker/cron) تا تقویم را poll و جدول‌ها را پر کند؛ API فقط می‌خواند.

## نکات حیاتی

- **تأخیر فید**: بعد از اولین رویداد بزرگ (مثلاً NFP بعدی)،
  `surprise_engine.feed_latency_report()` را اجرا کن. اگر میانه تأخیر
  بالای ~۵ ثانیه بود، Finnhub را با منبع سریع‌تری جایگزین کن —
  این تنها وابستگی پروژه است که نمی‌شود با کد جبرانش کرد.
- **نام رویدادها در EVENT_MAP** را با خروجی واقعی API تطبیق بده؛
  عناوین Finnhub گاهی تغییر جزئی می‌کنند.
- این کد عمداً بدون Celery/Kafka است — برای یک کاربر و ده‌ها شاخص،
  یک حلقه ساده کاملاً کافی و قابل دیباگ‌تر است. صف و worker را
  وقتی اضافه کن که چند صد کاربر همزمان داری.
- **سلب مسئولیت**: خروجی این سیستم تحلیل آماری گذشته است، نه سیگنال
  خرید/فروش. عملکرد گذشته تضمین آینده نیست.

## فاز بعدی (به ترتیب اولویت)

1. ~~API لایه وب با FastAPI روی همین توابع~~ ✅ انجام شد — `app/api.py` (بالا را ببین)
2. ~~موتور لحن بانک مرکزی Fed/ECB + tone_score با LLM~~ ✅ انجام شد —
   `app/cb_tone.py` + اندپوینت‌های `/cb/latest` و `/cb/history` (بالا را ببین)
3. ~~داشبورد که از API بالا تغذیه شود~~ ✅ انجام شد — به‌جای اسکفولد سنگین Next.js
   داخل یک ریپوی پایتونی، یک داشبورد تک‌فایلی (`app/static/dashboard.html`) که
   خودِ FastAPI روی `/` سرو می‌کند؛ بدون build، هم‌origin، بدون مشکل CORS.
