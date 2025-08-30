from typing import Iterable, List, Tuple
from datetime import datetime
import psycopg2

from .db import get_connection


def ensure_tables() -> None:
    """Create minimal tables if not exist.
    - stock_symbols(symbol text primary key, name text, market text)
    - stock_prices(symbol text, trade_date date, open numeric, high numeric, low numeric, close numeric, volume bigint)
      primary key (symbol, trade_date)
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS stock_symbols (
            symbol TEXT PRIMARY KEY,
            name   TEXT,
            market TEXT
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS stock_prices (
            symbol TEXT NOT NULL,
            trade_date DATE NOT NULL,
            open NUMERIC,
            high NUMERIC,
            low NUMERIC,
            close NUMERIC,
            volume BIGINT,
            PRIMARY KEY(symbol, trade_date)
        );
        """
    )
    conn.commit()
    cur.close()
    conn.close()


def upsert_prices(rows: Iterable[Tuple[str, datetime, float, float, float, float, int]]) -> int:
    """Upsert price rows. Returns number of rows processed.

    rows: iterable of (symbol, trade_date, open, high, low, close, volume)
    """
    rows_list: List[Tuple[str, datetime, float, float, float, float, int]] = list(rows)
    if not rows_list:
        return 0

    conn = get_connection()
    cur = conn.cursor()
    args_str = ",".join(cur.mogrify("(%s,%s,%s,%s,%s,%s,%s)", r).decode("utf-8") for r in rows_list)
    # Use ON CONFLICT for upsert
    cur.execute(
        f"""
        INSERT INTO stock_prices(symbol, trade_date, open, high, low, close, volume)
        VALUES {args_str}
        ON CONFLICT (symbol, trade_date) DO UPDATE SET
          open = EXCLUDED.open,
          high = EXCLUDED.high,
          low = EXCLUDED.low,
          close = EXCLUDED.close,
          volume = EXCLUDED.volume
        """
    )
    affected = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()
    return affected
