"""اتصال به دیتابیس — یک pool ساده با psycopg."""
import os
from contextlib import contextmanager

from psycopg_pool import ConnectionPool

DSN = os.environ.get(
    "FX_DB_DSN",
    "postgresql://fx:fx@localhost:5432/fxmacro",
)

pool = ConnectionPool(DSN, min_size=1, max_size=8, open=True)


@contextmanager
def db():
    """با هر فراخوانی یک کانکشن از pool می‌گیرد و در پایان commit می‌کند."""
    with pool.connection() as conn:
        yield conn
