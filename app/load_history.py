"""بارگذاری داده تاریخی یک‌دقیقه‌ای از فایل‌های CSV (مثلاً Dukascopy/HistData).

موتور واکنش تاریخی بدون این داده کار نمی‌کند — اولین کاری که بعد از
راه‌اندازی دیتابیس باید انجام دهی همین است.

فرمت CSV مورد انتظار (خروجی استاندارد Dukascopy):
    timestamp,open,high,low,close,volume
    2024-01-02 00:00:00,1.10421,1.10433,1.10415,1.10429,123.4

اجرا:
    python load_history.py EURUSD /path/to/EURUSD_1m_2020_2025.csv
"""
import csv
import sys
from datetime import datetime, timezone

from db import db

BATCH = 5000


def load(symbol: str, path: str) -> None:
    rows, total = [], 0
    with open(path, newline="") as f, db() as conn:
        reader = csv.reader(f)
        header = next(reader)
        if header[0].lower() not in ("timestamp", "time", "date"):
            f.seek(0)
            reader = csv.reader(f)
        for r in reader:
            ts = datetime.fromisoformat(r[0]).replace(tzinfo=timezone.utc)
            rows.append((symbol, ts, r[1], r[2], r[3], r[4],
                         r[5] if len(r) > 5 else None))
            if len(rows) >= BATCH:
                _flush(conn, rows)
                total += len(rows)
                rows.clear()
                print(f"\r{total:,} rows", end="")
        if rows:
            _flush(conn, rows)
            total += len(rows)
    print(f"\n{symbol}: {total:,} کندل وارد شد")


def _flush(conn, rows):
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO price_ohlc_1m
               (symbol, ts, open, high, low, close, volume)
               VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
            rows,
        )


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: python load_history.py SYMBOL file.csv")
    load(sys.argv[1].upper(), sys.argv[2])
