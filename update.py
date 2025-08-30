from flask import Flask, request, jsonify
from datetime import datetime
import math

import yfinance as yf

from lib.storage import ensure_tables, upsert_prices

app = Flask(__name__)


@app.route('/', methods=['POST', 'GET'])
def update_prices():
    """Update recent daily prices for a symbol into Neon.

    Query params:
      - symbol: e.g. 2330.TW (required)
      - days: integer, number of recent days to fetch (default: 30, max: 365)

    Example:
      GET /api/update?symbol=2330.TW&days=30
    """
    symbol = request.args.get('symbol') or request.form.get('symbol')
    if not symbol:
        return jsonify({'success': False, 'message': 'symbol is required, e.g. 2330.TW'}), 400

    try:
        days_str = request.args.get('days') or request.form.get('days') or '30'
        days = int(days_str)
        days = max(1, min(days, 365))
    except ValueError:
        return jsonify({'success': False, 'message': 'days must be an integer'}), 400

    try:
        ensure_tables()

        # Fetch recent daily data with yfinance
        df = yf.download(symbol, period=f"{days}d", interval="1d", auto_adjust=False, progress=False)
        if df is None or df.empty:
            return jsonify({'success': False, 'symbol': symbol, 'rows_written': 0, 'message': 'no data returned'}), 200

        df = df.reset_index()  # ensure Date column present
        rows = []
        for _, r in df.iterrows():
            # Some rows may have NaN; coerce to None for DB
            def nz(v):
                if v is None:
                    return None
                try:
                    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                        return None
                except Exception:
                    pass
                return v

            dt = r['Date']
            # yfinance returns Timestamp; ensure date
            if hasattr(dt, 'date'):
                trade_date = dt.date()
            else:
                # try parse
                trade_date = datetime.fromisoformat(str(dt)).date()

            rows.append(
                (
                    symbol,
                    trade_date,
                    nz(float(r.get('Open')) if 'Open' in r else None),
                    nz(float(r.get('High')) if 'High' in r else None),
                    nz(float(r.get('Low')) if 'Low' in r else None),
                    nz(float(r.get('Close')) if 'Close' in r else None),
                    int(r.get('Volume')) if 'Volume' in r and not math.isnan(r.get('Volume')) else 0,
                )
            )

        written = upsert_prices(rows)
        return jsonify({'success': True, 'symbol': symbol, 'days_requested': days, 'rows_written': written})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
