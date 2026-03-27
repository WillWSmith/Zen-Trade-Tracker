import sqlite3
import datetime
import os
import sys
import requests
import yfinance as yf
import pandas as pd
import webview
import csv

APP_DATA_DIR = os.path.join(os.environ.get('APPDATA', ''), 'ZenTradeTracker')
os.makedirs(APP_DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(APP_DATA_DIR, 'trades_local.db')

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS portfolios (id INTEGER PRIMARY KEY, name TEXT UNIQUE)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS trades (
                        id INTEGER PRIMARY KEY, portfolio_id INTEGER, ticker TEXT, type TEXT,
                        shares REAL, price REAL, date TEXT, FOREIGN KEY(portfolio_id) REFERENCES portfolios(id))''')
    conn.commit()
    conn.close()

def calculate_stop_gap(price, trigger_price):
    if price < 1.00:
        gap = max(trigger_price * 0.02, 0.02)
    elif price < 5.00:
        gap = max(trigger_price * 0.015, 0.03)
    else:
        gap = max(trigger_price * 0.01, 0.05)
    return round(trigger_price - gap, 2)

def get_earnings_warning(ticker_obj):
    """
    Returns (has_upcoming_earnings, days_until, date_str).
    Flags earnings within 21 days as overnight swing risk.
    Uses a hard 5s timeout on .calendar to avoid blocking the scanner loop.
    """
    try:
        import signal

        # --- timeout guard (Unix only; Windows falls back to bare call) ---
        def _fetch():
            return ticker_obj.calendar

        cal = None
        if hasattr(signal, 'SIGALRM'):
            def _handler(signum, frame):
                raise TimeoutError
            signal.signal(signal.SIGALRM, _handler)
            signal.alarm(5)
            try:
                cal = _fetch()
            except TimeoutError:
                return False, None, None
            finally:
                signal.alarm(0)
        else:
            cal = _fetch()

        if cal is None:
            return False, None, None

        earnings_dates = None
        if isinstance(cal, dict):
            earnings_dates = cal.get('Earnings Date', None)
        elif hasattr(cal, 'loc'):
            try:
                earnings_dates = cal.loc['Earnings Date'].tolist()
            except Exception:
                pass

        if not earnings_dates:
            return False, None, None

        now = datetime.datetime.now()
        for ed in earnings_dates:
            if hasattr(ed, 'to_pydatetime'):
                ed = ed.to_pydatetime()
            elif not isinstance(ed, datetime.datetime):
                continue
            ed = ed.replace(tzinfo=None)
            delta = (ed - now).days
            if 0 <= delta <= 21:
                return True, delta, ed.strftime('%b %d')

        return False, None, None
    except Exception:
        return False, None, None


def _safe_yf_download(tickers, **kwargs):
    """
    Wraps yf.download and normalises the result to a consistent
    multi-column DataFrame regardless of how many tickers are passed.
    Returns None on failure so callers can bail cleanly.
    """
    if not tickers:
        return None
    try:
        data = yf.download(list(set(tickers)), progress=False, **kwargs)
        if data is None or data.empty:
            return None
        # yf sometimes returns a flat Series or single-level columns for 1 ticker
        if isinstance(data.columns, pd.MultiIndex):
            return data
        # Single ticker: promote to MultiIndex so callers don't need special-casing
        if len(tickers) == 1:
            ticker = list(tickers)[0]
            data.columns = pd.MultiIndex.from_tuples([(col, ticker) for col in data.columns])
        return data
    except Exception:
        return None


class BackendAPI:
    def __init__(self):
        self.window = None
        self.is_maximized = False
        self._dashboard_cache = {}
        self._cache_ttl_seconds = 60

    def minimize(self):
        if self.window: self.window.minimize()

    def toggle_maximize(self):
        if self.window:
            if self.is_maximized:
                self.window.resize(1280, 760)
                if os.name == 'nt':
                    import ctypes
                    user32 = ctypes.windll.user32
                    sw = user32.GetSystemMetrics(0)
                    sh = user32.GetSystemMetrics(1)
                    self.window.move(int((sw - 1280) / 2), int((sh - 760) / 2))
                self.is_maximized = False
            else:
                if os.name == 'nt':
                    import ctypes
                    from ctypes import wintypes
                    user32 = ctypes.windll.user32
                    rect = wintypes.RECT()
                    user32.SystemParametersInfoW(48, 0, ctypes.byref(rect), 0)
                    self.window.resize(rect.right - rect.left, rect.bottom - rect.top)
                    self.window.move(rect.left, rect.top)
                else:
                    self.window.maximize()
                self.is_maximized = True

    def close_app(self):
        if self.window: self.window.destroy()

    def get_portfolios(self):
        conn = sqlite3.connect(DB_PATH)
        portfolios = {name: pid for pid, name in conn.execute("SELECT id, name FROM portfolios").fetchall()}
        conn.close()
        return portfolios

    def add_portfolio(self, name):
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.execute("INSERT INTO portfolios (name) VALUES (?)", (name.strip(),))
            conn.commit(); conn.close()
        except: pass

    def edit_portfolio(self, pid, name):
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.execute("UPDATE portfolios SET name=? WHERE id=?", (name.strip(), pid))
            conn.commit(); conn.close()
        except: pass

    def delete_portfolio(self, pid):
        conn = sqlite3.connect(DB_PATH)
        conn.execute("DELETE FROM trades WHERE portfolio_id=?", (pid,))
        conn.execute("DELETE FROM portfolios WHERE id=?", (pid,))
        conn.commit(); conn.close()
        self._dashboard_cache.pop(str(pid), None)

    def add_trade(self, pid, ticker, type, shares, price):
        conn = sqlite3.connect(DB_PATH)
        conn.execute("INSERT INTO trades (portfolio_id, ticker, type, shares, price, date) VALUES (?, ?, ?, ?, ?, ?)",
                     (pid, ticker, type, shares, price, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit(); conn.close()
        self._dashboard_cache.pop(str(pid), None)

    def get_dashboard_data(self, pid, timeframe="All Time"):
        pid_key = str(pid)
        now = datetime.datetime.now()

        if pid_key in self._dashboard_cache:
            tf_cache = self._dashboard_cache[pid_key].get(timeframe)
            if tf_cache:
                age = (now - tf_cache['ts']).total_seconds()
                if age < self._cache_ttl_seconds:
                    return tf_cache['data']

        conn = sqlite3.connect(DB_PATH)
        raw_trades = conn.execute(
            "SELECT ticker, type, shares, price, date FROM trades WHERE portfolio_id=? ORDER BY date ASC", (pid,)
        ).fetchall()
        first_trade_query = conn.execute("SELECT MIN(date) FROM trades WHERE portfolio_id=?", (pid,)).fetchone()
        conn.close()

        holdings_dict = {}
        realized_gl = 0.0
        total_cash = 0.0
        net_deposits = 0.0
        history_enriched = []

        for ticker, t_type, shares, price, date in raw_trades:
            trade_gl = None
            if t_type == 'Deposit':
                total_cash += shares
                net_deposits += shares
            elif t_type == 'Withdraw':
                total_cash -= shares
                net_deposits -= shares
            elif t_type == 'Dividend':
                total_cash += (shares * price)
            elif t_type == 'Buy':
                total_cash -= (shares * price)
                if ticker not in holdings_dict: holdings_dict[ticker] = {'shares': 0, 'avg_cost': 0.0}
                h = holdings_dict[ticker]
                total_cost = (h['shares'] * h['avg_cost']) + (shares * price)
                h['shares'] += shares
                h['avg_cost'] = total_cost / h['shares']
            elif t_type == 'Sell':
                total_cash += (shares * price)
                if ticker not in holdings_dict: holdings_dict[ticker] = {'shares': 0, 'avg_cost': 0.0}
                h = holdings_dict[ticker]
                trade_gl = (price - h['avg_cost']) * shares
                realized_gl += trade_gl
                h['shares'] -= shares
                if h['shares'] <= 0:
                    h['shares'] = 0
                    h['avg_cost'] = 0.0

            history_enriched.append({
                "date": date, "type": t_type, "ticker": ticker,
                "shares": float(shares), "price": float(price),
                "trade_gl": float(trade_gl) if trade_gl is not None else None
            })

        history_enriched.reverse()
        active_tickers = [t for t, d in holdings_dict.items() if d['shares'] > 0]
        unique_tickers = list(set([t[0] for t in raw_trades if t[0] != 'CASH']))

        total_market_value = 0.0
        total_book_value = 0.0
        total_prev_market_value = 0.0
        total_today_dlr = 0.0
        holdings_array = []

        for ticker in active_tickers:
            data = holdings_dict[ticker]
            shares = data['shares']
            avg_cost = data['avg_cost']
            try:
                fast_info = yf.Ticker(ticker).fast_info
                current_price = fast_info.last_price
                prev_close = fast_info.previous_close
            except:
                current_price = avg_cost
                prev_close = avg_cost

            if pd.isna(current_price): current_price = avg_cost
            if pd.isna(prev_close): prev_close = current_price

            book_val = shares * avg_cost
            market_val = shares * current_price
            prev_market_val = shares * prev_close

            total_book_value += book_val
            total_market_value += market_val
            total_prev_market_value += prev_market_val
            total_today_dlr += (market_val - prev_market_val)

            holdings_array.append({
                "ticker": ticker, "shares": float(shares), "avg_cost": float(avg_cost),
                "current_price": float(current_price), "unreal_dlr": float(market_val - book_val),
                "market_val": float(market_val)
            })

        total_account_value = total_market_value + total_cash
        unreal_total_dlr = total_market_value - total_book_value
        unreal_total_pct = (unreal_total_dlr / total_book_value * 100) if total_book_value > 0 else 0.0
        today_pct = (total_today_dlr / total_prev_market_value * 100) if total_prev_market_value > 0 else 0.0

        for h in holdings_array:
            h["allocation"] = (h["market_val"] / total_account_value * 100) if total_account_value > 0 else 0.0

        chart_dates = []; chart_values = []
        if raw_trades and first_trade_query and first_trade_query[0]:
            first_trade_date = datetime.datetime.strptime(first_trade_query[0], "%Y-%m-%d %H:%M:%S")
            now_dt = datetime.datetime.now()
            if timeframe == "1M": requested_start = now_dt - datetime.timedelta(days=30)
            elif timeframe == "1Y": requested_start = now_dt - datetime.timedelta(days=365)
            else: requested_start = first_trade_date
            actual_start_date = max(requested_start, first_trade_date)

            trades_df = pd.DataFrame(raw_trades, columns=['ticker', 'type', 'shares', 'price', 'date'])
            trades_df['date'] = pd.to_datetime(trades_df['date'], errors='coerce').dt.floor('D')
            trades_df = trades_df.dropna(subset=['date'])

            def get_share_change(row):
                if row['type'] == 'Buy': return row['shares']
                elif row['type'] == 'Sell': return -row['shares']
                return 0
            trades_df['share_change'] = trades_df.apply(get_share_change, axis=1)

            def get_cash_change(row):
                cost = row['shares'] * row['price']
                if row['type'] == 'Buy': return -cost
                elif row['type'] == 'Sell': return cost
                elif row['type'] == 'Deposit': return row['shares']
                elif row['type'] == 'Withdraw': return -row['shares']
                elif row['type'] == 'Dividend': return cost
                return 0
            trades_df['cash_change'] = trades_df.apply(get_cash_change, axis=1)

            full_range = pd.date_range(start=trades_df['date'].min(), end=pd.Timestamp(now_dt).floor('D'), freq='D')
            daily_cash = trades_df.groupby('date')['cash_change'].sum().reindex(full_range, fill_value=0).cumsum()
            daily_equity = pd.Series(0.0, index=full_range)

            stock_trades = trades_df[trades_df['type'].isin(['Buy', 'Sell'])]
            if not stock_trades.empty:
                daily_changes = stock_trades.groupby(['date', 'ticker'])['share_change'].sum().unstack(fill_value=0)
                balances = daily_changes.reindex(full_range, fill_value=0).cumsum().fillna(0)
                tickers_to_fetch = list(daily_changes.columns)
                if tickers_to_fetch:
                    try:
                        price_data = yf.download(tickers_to_fetch, start=full_range.min().strftime('%Y-%m-%d'), progress=False)['Close']
                        if isinstance(price_data, pd.Series):
                            price_data = price_data.to_frame(name=tickers_to_fetch[0])
                        if not price_data.empty:
                            if price_data.index.tz: price_data.index = price_data.index.tz_localize(None)
                            hist_prices = price_data.reindex(full_range).ffill().bfill().fillna(0)
                            daily_equity = (balances * hist_prices).sum(axis=1)
                    except: pass

            total_acc = daily_cash + daily_equity
            total_acc = total_acc[total_acc.index >= actual_start_date]
            chart_dates = [d.strftime('%b %d, %Y') for d in total_acc.index]
            chart_values = [float(x) for x in total_acc.values]

        realized_pct = (realized_gl / net_deposits * 100) if net_deposits > 0 else 0.0

        result = {
            "total_account": float(total_account_value), "total_cash": float(total_cash),
            "today_dlr": float(total_today_dlr), "today_pct": float(today_pct),
            "total_market": float(total_market_value), "unreal_dlr": float(unreal_total_dlr),
            "unreal_pct": float(unreal_total_pct), "realized_gl": float(realized_gl),
            "realized_pct": realized_pct,
            "holdings": holdings_array, "history": history_enriched, "unique_tickers": unique_tickers,
            "chart_dates": chart_dates, "chart_values": [0 if pd.isna(x) else float(x) for x in chart_values]
        }

        if pid_key not in self._dashboard_cache: self._dashboard_cache[pid_key] = {}
        self._dashboard_cache[pid_key][timeframe] = {'ts': datetime.datetime.now(), 'data': result}
        return result

    def run_swing_scanner(self, cash_available, total_account=100.0):
        try:
            eval_cash = max(cash_available, 5.0)
            eval_account = max(total_account, 100.0)
            full_universe = []
            tv_url = "https://scanner.tradingview.com/canada/scan"

            for exchange in ["TSXV", "TSX"]:
                try:
                    payload = {
                        "filter": [{"left": "exchange", "operation": "equal", "right": exchange}],
                        "options": {"lang": "en"}, "markets": ["canada"], "columns": ["name", "volume"],
                        "sort": {"sortBy": "volume", "sortOrder": "desc"}, "range": [0, 150]
                    }
                    resp = requests.post(tv_url, json=payload, timeout=10)
                    resp.raise_for_status()
                    suffix = ".V" if exchange == "TSXV" else ".TO"
                    full_universe += [
                        f"{item['d'][0].replace('.', '-')}{suffix}"
                        for item in resp.json().get("data", []) if item.get("d")
                    ]
                except Exception:
                    # One exchange failing shouldn't abort the whole scan
                    continue

            if not full_universe:
                return [{"ticker": "ERROR", "setup": "TradingView scanner returned no tickers. Check network or API availability."}]

            data = _safe_yf_download(list(set(full_universe)), period="1y")
            if data is None:
                return [{"ticker": "ERROR", "setup": "yfinance download failed. Check your internet connection."}]

            # Normalise to top-level field access regardless of MultiIndex structure
            try:
                close_data = data['Close']
                high_data  = data['High']
                low_data   = data['Low']
                vol_data   = data['Volume']
            except KeyError:
                return [{"ticker": "ERROR", "setup": "Unexpected data format returned by yfinance."}]

            # Ensure DataFrames, not Series (happens when exactly 1 ticker returns data)
            if isinstance(close_data, pd.Series):
                t = close_data.name or full_universe[0]
                close_data = close_data.to_frame(t)
                high_data  = high_data.to_frame(t)
                low_data   = low_data.to_frame(t)
                vol_data   = vol_data.to_frame(t)

            suggestions = []
            VOL_FLOOR_VENTURE = 400_000
            VOL_FLOOR_TSX     = 1_000_000

            for ticker in close_data.columns:
                try:
                    c_s = close_data[ticker].dropna()
                    h_s = high_data[ticker].dropna()
                    l_s = low_data[ticker].dropna()
                    v_s = vol_data[ticker].dropna()
                    if len(c_s) < 200: continue

                    curr = float(c_s.iloc[-1])
                    if curr <= 0: continue

                    avg_v = float(v_s.tail(20).mean())
                    is_venture = '.V' in ticker

                    # 1. LIQUIDITY & VOLUME SPIKE
                    vol_floor = VOL_FLOOR_VENTURE if is_venture else VOL_FLOOR_TSX
                    # FIX: Use 3-day average volume for spike check instead of single last day,
                    # to avoid dropping valid setups that happened to scan on a lighter session.
                    recent_v  = float(v_s.tail(3).mean())
                    vol_mult  = 1.5 if is_venture else 1.2
                    dollar_vol = avg_v * curr
                    if dollar_vol < vol_floor or recent_v < (avg_v * vol_mult):
                        continue

                    # 2. VOLATILITY GUARD (ATR 14)
                    tr = pd.concat([
                        (h_s - l_s),
                        (h_s - c_s.shift(1)).abs(),
                        (l_s - c_s.shift(1)).abs()
                    ], axis=1).max(axis=1)
                    atr = tr.rolling(14).mean().iloc[-1]
                    if pd.isna(atr) or (atr / curr) > 0.08: continue

                    # 3. RSI & ADX
                    plus_di  = 100 * ((h_s.diff().clip(lower=0)).rolling(14).sum() / tr.rolling(14).sum())
                    minus_di = 100 * ((-l_s.diff().clip(lower=0)).rolling(14).sum() / tr.rolling(14).sum())
                    adx_raw  = (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, float('nan')).abs() * 100
                    adx      = adx_raw.rolling(14).mean()
                    curr_adx = float(adx.iloc[-1]) if not pd.isna(adx.iloc[-1]) else 0.0

                    delta   = c_s.diff()
                    gain    = delta.clip(lower=0).ewm(com=13).mean()
                    loss    = (-delta.clip(upper=0)).ewm(com=13).mean()
                    # Guard against division by zero in RSI
                    rsi     = gain.combine(loss, lambda g, l: 100 if l == 0 else 100 - (100 / (1 + g / l)))
                    curr_rsi = float(rsi.iloc[-1]) if not pd.isna(rsi.iloc[-1]) else 50.0

                    if curr_adx < 25 or curr_rsi < 35 or curr_rsi > 75: continue

                    # 4. TREND CONFIRMATION
                    h52    = float(h_s.tail(252).max())
                    sma50  = float(c_s.tail(50).mean())
                    sma200 = float(c_s.tail(200).mean())

                    if is_venture:
                        if curr < (h52 * 0.85) or curr < sma50: continue
                    else:
                        if curr < (h52 * 0.75) or curr < sma200: continue

                    # FIX: Loosened entry filter — original required BOTH conditions simultaneously,
                    # which was too restrictive for trending stocks. Now uses OR logic: pass if the
                    # stock is either not extended vs SMA50 OR has recent momentum.
                    sma10 = float(c_s.tail(10).mean())
                    if curr > (sma50 * 1.25) and curr > sma10:
                        continue  # Extended AND losing short-term momentum — skip

                    # 5. EARNINGS PROXIMITY CHECK
                    ticker_obj = yf.Ticker(ticker)
                    has_earnings, days_until, earn_date_str = get_earnings_warning(ticker_obj)

                    # 6. SECTOR LOOKUP
                    try:
                        info = ticker_obj.info
                        raw_sector = info.get('sector', '') or ''
                        sector_map = {
                            'Energy': 'Energy', 'Basic Materials': 'Materials',
                            'Materials': 'Materials', 'Technology': 'Technology',
                            'Financial Services': 'Financials', 'Financials': 'Financials',
                            'Healthcare': 'Healthcare', 'Health Care': 'Healthcare',
                            'Industrials': 'Industrials',
                        }
                        sector = sector_map.get(raw_sector, 'Unknown')
                    except Exception:
                        sector = 'Unknown'

                    atr_mult = 2.5 if is_venture else 2.0
                    stop = curr - (atr * atr_mult)
                    risk = curr - stop

                    if risk <= 0:
                        continue  # Guard against degenerate ATR

                    if eval_account < 500:
                        shares = int((eval_account * 0.25) / curr)
                    elif eval_account < 2500:
                        shares = int((eval_account * 0.20) / curr)
                    else:
                        shares = int((eval_account * 0.02) / risk)

                    shares = min(shares, int(eval_cash / curr))
                    if shares <= 0: continue

                    suggestions.append({
                        "ticker":           ticker,
                        "buy_price":        curr,
                        "stop_trigger":     round(stop, 2),
                        "stop_limit":       calculate_stop_gap(curr, stop),
                        "take_profit":      round(curr + (risk * 2.5), 2),
                        "shares":           shares,
                        "total_cost":       round(shares * curr, 2),
                        "setup":            "Venture Momentum" if is_venture else "Institutional Swing",
                        "sector":           sector,
                        "adx":              curr_adx,
                        "earnings_warning": has_earnings,
                        "earnings_days":    days_until,
                        "earnings_date":    earn_date_str,
                    })

                except Exception:
                    # Per-ticker failure should never abort the entire scan
                    continue

            suggestions.sort(key=lambda x: x['adx'], reverse=True)
            return suggestions[:8] if suggestions else [{"ticker": "INFO", "setup": "No setups matched the current Zen criteria. Markets may be choppy — check back tomorrow."}]

        except Exception as e:
            return [{"ticker": "ERROR", "setup": str(e)}]

    def audit_portfolio(self, tickers, portfolio_id=None):
        if not tickers: return []
        conn = sqlite3.connect(DB_PATH)
        try:
            if portfolio_id is not None:
                raw_trades = conn.execute(
                    "SELECT ticker, type, shares, price FROM trades WHERE portfolio_id=?", (portfolio_id,)
                ).fetchall()
            else:
                raw_trades = conn.execute("SELECT ticker, type, shares, price FROM trades").fetchall()

            holdings = {}
            for t, ty, s, p in raw_trades:
                if t not in holdings: holdings[t] = {'shares': 0, 'avg_cost': 0.0}
                if ty == 'Buy':
                    cost = (holdings[t]['shares'] * holdings[t]['avg_cost']) + (s * p)
                    holdings[t]['shares'] += s
                    holdings[t]['avg_cost'] = cost / holdings[t]['shares']
                elif ty == 'Sell':
                    holdings[t]['shares'] -= s

            data = yf.download(tickers, period="1y", progress=False)
            results = []

            if data is None or data.empty:
                return [{"ticker": "ERROR", "reason": "yfinance returned no data for these tickers."}]

            close_df = data['Close'] if len(tickers) > 1 else data[['Close']]
            high_df  = data['High']  if len(tickers) > 1 else data[['High']]
            low_df   = data['Low']   if len(tickers) > 1 else data[['Low']]

            # If a single ticker returned, columns may just be field names not tickers
            if len(tickers) == 1 and tickers[0] not in close_df.columns:
                close_df = close_df.rename(columns=lambda _: tickers[0])
                high_df  = high_df.rename(columns=lambda _: tickers[0])
                low_df   = low_df.rename(columns=lambda _: tickers[0])

            for ticker in tickers:
                if ticker not in close_df.columns: continue
                c_s = close_df[ticker].dropna()
                h_s = high_df[ticker].dropna()
                l_s = low_df[ticker].dropna()
                if len(c_s) < 15: continue

                curr = float(c_s.iloc[-1])

                if portfolio_id is not None:
                    buy_date_row = conn.execute(
                        "SELECT MIN(date) FROM trades WHERE ticker=? AND type='Buy' AND portfolio_id=?",
                        (ticker, portfolio_id)
                    ).fetchone()
                else:
                    buy_date_row = conn.execute(
                        "SELECT MIN(date) FROM trades WHERE ticker=? AND type='Buy'", (ticker,)
                    ).fetchone()

                buy_date_str = buy_date_row[0] if buy_date_row else None
                if buy_date_str:
                    buy_date = pd.to_datetime(buy_date_str, errors='coerce')
                    if buy_date is not pd.NaT:
                        buy_date = buy_date.tz_localize(None)
                        valid_highs = h_s[h_s.index >= buy_date]
                        high_water_mark = float(valid_highs.max()) if not valid_highs.empty else curr
                    else:
                        high_water_mark = curr
                else:
                    high_water_mark = curr

                h = holdings.get(ticker, {'shares': 0, 'avg_cost': curr})
                if h['shares'] <= 0: continue

                avg_c = h['avg_cost']
                is_venture = '.V' in ticker

                tr = pd.concat([
                    (h_s - l_s),
                    (h_s - c_s.shift(1)).abs(),
                    (l_s - c_s.shift(1)).abs()
                ], axis=1).max(axis=1)
                atr = tr.rolling(14).mean().iloc[-1]

                atr_mult = 2.5 if is_venture else 2.0
                buffer = atr * atr_mult
                stop   = round(high_water_mark - buffer, 2)

                target_pct = 0.25 if is_venture else 0.15
                target_p   = avg_c * (1 + target_pct)
                if high_water_mark >= target_p:
                    stop = max(stop, round(avg_c, 2))
                if stop >= curr:
                    stop = round(curr * 0.98, 2)

                upside_from_target = ((curr - target_p) / target_p * 100) if target_p > 0 else 0.0

                if curr <= stop:
                    status = "SELL"; reason = "Volatility Breach"; color = "text-[#EF4444]"
                elif curr >= target_p:
                    if upside_from_target >= 15:
                        status = "TRIM"; reason = f"Target +{upside_from_target:.0f}% — trim aggressively"; color = "text-[#F59E0B]"
                    else:
                        status = "TRIM"; reason = f"Target hit (+{upside_from_target:.0f}%) — consider partial exit"; color = "text-[#22C55E]"
                else:
                    status = "HOLD"; reason = "Healthy"; color = "text-[#22C55E]"

                results.append({
                    "ticker": ticker, "current_price": curr,
                    "stop_trigger": stop, "stop_limit": calculate_stop_gap(curr, stop),
                    "status": status, "color": color, "reason": reason,
                })

            return results

        except Exception as e:
            return [{"ticker": "ERROR", "reason": str(e)}]
        finally:
            # FIX: Always close the connection, even if yf.download or processing raises
            conn.close()

    def export_csv(self):
        if self.window:
            path = self.window.create_file_dialog(webview.SAVE_DIALOG, save_filename='ZenTrades.csv')
            if path:
                conn = sqlite3.connect(DB_PATH)
                trades = conn.execute(
                    "SELECT portfolios.name, ticker, type, shares, price, date "
                    "FROM trades JOIN portfolios ON trades.portfolio_id = portfolios.id"
                ).fetchall()
                conn.close()
                with open(path[0], 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow(['Portfolio', 'Ticker', 'Type', 'Shares', 'Price', 'Date'])
                    writer.writerows(trades)

    def import_csv(self):
        if self.window:
            path = self.window.create_file_dialog(webview.OPEN_DIALOG, file_types=('CSV Files (*.csv)',))
            if path:
                try:
                    df = pd.read_csv(path[0])

                    # FIX: Validate required columns BEFORE touching the database
                    required_cols = {'Portfolio', 'Ticker', 'Type', 'Shares', 'Price', 'Date'}
                    missing = required_cols - set(df.columns)
                    if missing:
                        if self.window:
                            self.window.evaluate_js(
                                f'alert("Import failed: CSV is missing columns: {", ".join(missing)}")'
                            )
                        return

                    conn = sqlite3.connect(DB_PATH)
                    try:
                        conn.execute("DELETE FROM trades")
                        conn.execute("DELETE FROM portfolios")
                        for p in df['Portfolio'].unique():
                            conn.execute("INSERT INTO portfolios (name) VALUES (?)", (str(p),))
                        for _, r in df.iterrows():
                            pid = conn.execute(
                                "SELECT id FROM portfolios WHERE name=?", (str(r['Portfolio']),)
                            ).fetchone()[0]
                            conn.execute(
                                "INSERT INTO trades (portfolio_id, ticker, type, shares, price, date) VALUES (?, ?, ?, ?, ?, ?)",
                                (pid, r['Ticker'], r['Type'], r['Shares'], r['Price'], r['Date'])
                            )
                        conn.commit()
                        self._dashboard_cache = {}
                        self.window.evaluate_js('loadPortfolios();')
                    except Exception as e:
                        conn.rollback()
                        if self.window:
                            self.window.evaluate_js(f'alert("Import failed during database write: {str(e)}")')
                    finally:
                        conn.close()
                except Exception as e:
                    if self.window:
                        self.window.evaluate_js(f'alert("Import failed: could not read CSV file. {str(e)}")')


def get_entrypoint():
    if hasattr(sys, '_MEIPASS'): return os.path.join(sys._MEIPASS, 'gui', 'index.html')
    return os.path.join(os.path.dirname(__file__), 'gui', 'index.html')

if __name__ == '__main__':
    init_db()
    try: import pyi_splash; pyi_splash.close()
    except ImportError: pass
    api = BackendAPI()
    window = webview.create_window(
        'Zen Portfolios', url=get_entrypoint(), js_api=api,
        width=1280, height=760, background_color='#0a0a0c',
        resizable=True, frameless=True
    )
    api.window = window
    webview.start()
