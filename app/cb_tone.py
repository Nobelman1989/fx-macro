"""موتور لحن بانک مرکزی (فاز بعدی #۲).

بیانیه‌ی سیاست پولی Fed/ECB را می‌گیرد، با یک LLM لحن آن را از منظر
هاوکیش/داویش می‌سنجد، نسبت به بیانیه‌ی قبلی diff می‌گیرد، و نتیجه را در
جدول `cb_statements` ذخیره می‌کند.

  tone_score: -1.0 (کاملاً Dovish) ... +1.0 (کاملاً Hawkish)

ورود داده (ingest) عمداً در API نیست (API فقط read است). از CLI یا حلقه‌ی
زمان‌بندی صداش بزن:

    python cb_tone.py FED https://www.federalreserve.gov/.../monetary20260611a.htm
    python cb_tone.py ECB <url>

متغیر محیطی لازم برای تحلیل: ANTHROPIC_API_KEY
"""
import json
import logging
import os
from datetime import datetime, timezone

import httpx

from db import db

log = logging.getLogger("cb_tone")

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
MODEL = os.environ.get("CB_TONE_MODEL", "claude-sonnet-4-5")

# صفحه‌ی فهرست بیانیه‌ها (نقطه‌ی شروع؛ معمولاً باید لینک آخرین بیانیه را از این‌جا برداری)
SOURCES = {
    "FED": "https://www.federalreserve.gov/newsevents/pressreleases/monetary.htm",
    "ECB": "https://www.ecb.europa.eu/press/govcdec/mopo/html/index.en.html",
}

SYSTEM_PROMPT = (
    "تو یک تحلیلگر ارشد سیاست پولی هستی. متن بیانیه‌ی بانک مرکزی را بخوان و "
    "لحن آن را از منظر هاوکیش (انقباضی) در برابر داویش (انبساطی) بسنج. "
    "خروجی را فقط به‌صورت یک JSON معتبر با همین سه کلید بده:\n"
    '  "tone_score": عددی اعشاری بین -1.0 (کاملاً Dovish) تا +1.0 (کاملاً Hawkish).\n'
    '  "tone_summary": حداکثر دو جمله‌ی فارسی که دلیل این امتیاز را می‌گوید.\n'
    '  "diff_vs_prev": اگر متن بیانیه‌ی قبلی هم داده شد، مهم‌ترین تغییر لحن یا '
    "عبارت کلیدی نسبت به آن را در یک جمله‌ی فارسی بنویس؛ اگر متن قبلی نبود، مقدار null بده.\n"
    "فقط و فقط JSON برگردان، بدون هیچ متن اضافه‌ای قبل یا بعد از آن."
)


def fetch_text(url: str) -> str:
    """متن خام یک صفحه‌ی بیانیه را استخراج می‌کند (تگ‌های ناوبری حذف می‌شوند)."""
    from bs4 import BeautifulSoup  # وارد کردن تنبل: فقط هنگام واکشی لازم است

    r = httpx.get(
        url, timeout=30, follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 (fx-macro cb_tone)"},
    )
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "form"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return "\n".join(lines)


def _extract_json(s: str) -> dict:
    """JSON را از خروجی مدل بیرون می‌کشد، حتی اگر متن اضافه داشته باشد."""
    try:
        return json.loads(s)
    except Exception:  # noqa: BLE001
        i, j = s.find("{"), s.rfind("}")
        if i != -1 and j > i:
            try:
                return json.loads(s[i:j + 1])
            except Exception:  # noqa: BLE001
                pass
    return {}


def analyze_tone(raw_text: str, prev_text: str | None = None) -> dict:
    """با LLM لحن متن را تحلیل می‌کند و {tone_score, tone_summary, diff_vs_prev} می‌دهد."""
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY تنظیم نشده است — تحلیل لحن ممکن نیست.")

    user = "متن بیانیه‌ی فعلی:\n" + raw_text[:12000]
    if prev_text:
        user += "\n\n---\nمتن بیانیه‌ی قبلی (برای مقایسه/diff):\n" + prev_text[:12000]

    r = httpx.post(
        ANTHROPIC_URL,
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": MODEL,
            "max_tokens": 600,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": user}],
        },
        timeout=60,
    )
    r.raise_for_status()
    data = r.json()
    text = "".join(
        b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"
    ).strip()
    parsed = _extract_json(text)

    score = parsed.get("tone_score")
    try:
        score = max(-1.0, min(1.0, float(score))) if score is not None else None
    except (TypeError, ValueError):
        score = None

    return {
        "tone_score": score,
        "tone_summary": parsed.get("tone_summary"),
        "diff_vs_prev": parsed.get("diff_vs_prev"),
    }


def _prev_text(conn, central_bank: str) -> str | None:
    cur = conn.execute(
        """SELECT raw_text FROM cb_statements
           WHERE central_bank = %s ORDER BY published_at DESC LIMIT 1""",
        (central_bank,),
    )
    row = cur.fetchone()
    return row[0] if row else None


def ingest(
    central_bank: str,
    doc_type: str = "statement",
    source_url: str | None = None,
    raw_text: str | None = None,
    published_at: datetime | None = None,
) -> dict:
    """بیانیه را واکشی/تحلیل و در cb_statements ذخیره می‌کند. id و نتیجه‌ی لحن را برمی‌گرداند."""
    central_bank = central_bank.upper()
    if raw_text is None:
        if not source_url:
            raise ValueError("باید یا raw_text یا source_url بدهی.")
        raw_text = fetch_text(source_url)
    if not raw_text.strip():
        raise ValueError("متن بیانیه خالی است.")

    published_at = published_at or datetime.now(timezone.utc)

    with db() as conn:
        prev = _prev_text(conn, central_bank)

    tone = analyze_tone(raw_text, prev)

    with db() as conn:
        cur = conn.execute(
            """INSERT INTO cb_statements
                (central_bank, published_at, doc_type, source_url, raw_text,
                 tone_score, tone_summary, diff_vs_prev)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
               RETURNING id""",
            (central_bank, published_at, doc_type, source_url, raw_text,
             tone["tone_score"], tone["tone_summary"], tone["diff_vs_prev"]),
        )
        new_id = cur.fetchone()[0]

    log.info("cb statement ingested: %s id=%s tone=%s",
             central_bank, new_id, tone["tone_score"])
    return {
        "id": new_id,
        "central_bank": central_bank,
        "published_at": published_at.isoformat(),
        **tone,
    }


def latest(central_bank: str) -> dict | None:
    """آخرین بیانیه‌ی تحلیل‌شده‌ی یک بانک مرکزی (بدون raw_text)."""
    with db() as conn:
        cur = conn.execute(
            """SELECT id, central_bank, published_at, doc_type, source_url,
                      tone_score, tone_summary, diff_vs_prev
               FROM cb_statements
               WHERE central_bank = %s ORDER BY published_at DESC LIMIT 1""",
            (central_bank.upper(),),
        )
        cols = [c.name for c in cur.description]
        row = cur.fetchone()
        return dict(zip(cols, row)) if row else None


def history(central_bank: str, limit: int = 20) -> list[dict]:
    """تاریخچه‌ی لحن یک بانک مرکزی (برای رسم روند هاوکیش/داویش)."""
    with db() as conn:
        cur = conn.execute(
            """SELECT id, central_bank, published_at, doc_type, source_url,
                      tone_score, tone_summary, diff_vs_prev
               FROM cb_statements
               WHERE central_bank = %s ORDER BY published_at DESC LIMIT %s""",
            (central_bank.upper(), limit),
        )
        cols = [c.name for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) < 2:
        sys.exit("usage: python cb_tone.py {FED|ECB|...} [statement_url]")
    cb = sys.argv[1].upper()
    url = sys.argv[2] if len(sys.argv) > 2 else SOURCES.get(cb)
    if not url:
        sys.exit(f"برای {cb} آدرس پیش‌فرضی نیست؛ یک URL مستقیم بده.")
    result = ingest(cb, "statement", url)
    print(json.dumps(result, ensure_ascii=False, indent=2))
