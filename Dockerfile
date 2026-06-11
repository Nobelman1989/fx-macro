# fx-macro API — production container (FastAPI + داشبورد روی /)
# ساخت محلی:   docker build -t fx-macro .
# اجرا محلی:   docker run -p 8000:8000 --env-file .env fx-macro
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# اول فقط وابستگی‌ها → کش لایه‌ای داکر
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# سپس کد و اسکیمای SQL
COPY app ./app
COPY sql ./sql

WORKDIR /app/app

# پلتفرم‌های ابری معمولاً پورت را با $PORT تزریق می‌کنند؛ پیش‌فرض ۸۰۰۰.
EXPOSE 8000
CMD ["sh", "-c", "uvicorn api:app --host 0.0.0.0 --port ${PORT:-8000}"]
