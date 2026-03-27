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
    Returns a tuple: (has_upcoming_earnings: bool, days_until: int or None, date_str: str or None)
    Flags any earnings within 21 days as a risk for overnight swing holds.
    """
    try:
        cal = ticker_obj.calendar
        if cal is None:
            return False, None, None

        # yfinance returns a dict with 'Earnings Date' as a list of Timestamps
        earnings_dates = None
        if isinstance(cal, dict):
            earnings_dates = cal.get('Earnings Date', None)
        elif hasattr(cal, 'loc'):
            # older yfinance returns a DataFrame
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


class BackendAPI:
    def __init__(self):
        self.window = None
        self.is_maximized = False
        # Simple in-memory cache: { pid: { tf: { 'ts': datetime, 'data': {...} } } }
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
        # Invalidate cache for this portfolio
        self._dashboard_cache.pop(str(pid), None)

    def add_trade(self, pid, ticker, type, shares, price):
        conn = sqlite3.connect(DB_PATH)
        conn.execute("INSERT INTO trades (portfolio_id, ticker, type, shares, price, date) VALUES (?, ?, ?, ?, ?, ?)",
                     (pid, ticker, type, shares, price, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit(); conn.close()
        # Invalidate cache so next load reflects the new trade
        self._dashboard_cache.pop(str(pid), None)

    def get_dashboard_data(self, pid, timeframe="All Time"):
        pid_key = str(pid)
        now = datetime.datetime.now()

        # --- Cache check ---
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
                # shares=1.0, price=payout amount (see submitDividend in frontend)
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
            trades_df['date'] = pd.to_datetime(trades_df['date']).dt.floor('D')

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
                    except:
                        pass

            total_acc = daily_cash + daily_equity
            total_acc = total_acc[total_acc.index >= actual_start_date]
            chart_dates = [d.strftime('%b %d, %Y') for d in total_acc.index]
            chart_values = [float(x) for x in total_acc.values]

        # --- FIX: realized_pct uses book value denominator for apples-to-apples comparison ---
        # We use net_deposits as the base (total capital committed), which is the most
        # intuitive denominator for "how much did I make on what I put in."
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

        # Store in cache
        pid_key = str(pid)
        if pid_key not in self._dashboard_cache:
            self._dashboard_cache[pid_key] = {}
        self._dashboard_cache[pid_key][timeframe] = {'ts': datetime.datetime.now(), 'data': result}

        return result

    # --- ZEN MASTER SCANNER (Fixed: sector lookup, earnings filter, volume floor, result cap) ---
    def run_swing_scanner(self, cash_available, total_account=100.0):
        try:
            eval_cash = max(cash_available, 5.0)
            eval_account = max(total_account, 100.0)
            full_universe = []
            tv_url = "https://scanner.tradingview.com/canada/scan"

            for exchange in ["TSXV", "TSX"]:
                payload = {
                    "filter": [{"left": "exchange", "operation": "equal", "right": exchange}],
                    "options": {"lang": "en"}, "markets": ["canada"], "columns": ["name", "volume"],
                    "sort": {"sortBy": "volume", "sortOrder": "desc"}, "range": [0, 150]
                }
                resp = requests.post(tv_url, json=payload, timeout=10)
                if resp.status_code == 200:
                    suffix = ".V" if exchange == "TSXV" else ".TO"
                    full_universe += [
                        f"{item['d'][0].replace('.', '-')}{suffix}"
                        for item in resp.json().get("data", []) if item.get("d")
                    ]

            data = yf.download(list(set(full_universe)), period="1y", progress=False)
            if 'Close' not in data: return []
            close_data, high_data, low_data, vol_data = data['Close'], data['High'], data['Low'], data['Volume']
            suggestions = []

            # FIX: Raise volume dollar floor — $250k is too thin for meaningful swing exits.
            # TSX.V floor: $400k/day; TSX floor: $1M/day.
            VOL_FLOOR_VENTURE = 400_000
            VOL_FLOOR_TSX     = 1_000_000

            for ticker in close_data.columns:
                c_s = close_data[ticker].dropna()
                h_s = high_data[ticker].dropna()
                l_s = low_data[ticker].dropna()
                v_s = vol_data[ticker].dropna()
                if len(c_s) < 200: continue

                curr = float(c_s.iloc[-1])
                avg_v = float(v_s.tail(20).mean())
                is_venture = '.V' in ticker

                # 1. LIQUIDITY & VOLUME SPIKE (fixed floors)
                vol_floor = VOL_FLOOR_VENTURE if is_venture else VOL_FLOOR_TSX
                vol_mult  = 2.0 if is_venture else 1.5
                dollar_vol = avg_v * curr
                if dollar_vol < vol_floor or float(v_s.iloc[-1]) < (avg_v * vol_mult):
                    continue

                # 2. VOLATILITY GUARD (ATR 14)
                tr = pd.concat([
                    (h_s - l_s),
                    (h_s - c_s.shift(1)).abs(),
                    (l_s - c_s.shift(1)).abs()
                ], axis=1).max(axis=1)
                atr = tr.rolling(14).mean().iloc[-1]
                if (atr / curr) > 0.08: continue

                # 3. RSI & ADX
                plus_di  = 100 * ((h_s.diff().clip(lower=0)).rolling(14).sum() / tr.rolling(14).sum())
                minus_di = 100 * ((-l_s.diff().clip(lower=0)).rolling(14).sum() / tr.rolling(14).sum())
                adx = (
                    (plus_di - minus_di).abs() / (plus_di + minus_di).abs() * 100
                ).rolling(14).mean()
                curr_adx = float(adx.iloc[-1])

                delta = c_s.diff()
                rsi = 100 - (100 / (
                    1 + (delta.clip(lower=0).ewm(com=13).mean() /
                         (-1 * delta.clip(upper=0).ewm(com=13).mean()))
                ))
                curr_rsi = float(rsi.iloc[-1])

                if curr_adx < 25 or curr_rsi < 35 or curr_rsi > 75: continue

                # 4. TREND CONFIRMATION
                h52   = float(h_s.tail(252).max())
                sma50  = float(c_s.tail(50).mean())
                sma200 = float(c_s.tail(200).mean())

                if is_venture:
                    if curr < (h52 * 0.85) or curr < sma50: continue
                else:
                    if curr < (h52 * 0.75) or curr < sma200: continue

                if curr < (sma50 * 1.25) and curr < float(c_s.tail(10).mean()):

                    # 5. EARNINGS PROXIMITY CHECK — flag overnight risk for swing holds
                    ticker_obj = yf.Ticker(ticker)
                    has_earnings, days_until, earn_date_str = get_earnings_warning(ticker_obj)

                    # FIX: Pull real sector from yfinance info
                    try:
                        info = ticker_obj.info
                        raw_sector = info.get('sector', '') or ''
                        # Normalize to our frontend color-map keys
                        sector_map = {
                            'Energy':                  'Energy',
                            'Basic Materials':         'Materials',
                            'Materials':               'Materials',
                            'Technology':              'Technology',
                            'Financial Services':      'Financials',
                            'Financials':              'Financials',
                            'Healthcare':              'Healthcare',
                            'Health Care':             'Healthcare',
                            'Industrials':             'Industrials',
                            'Consumer Cyclical':       'Unknown',
                            'Consumer Defensive':      'Unknown',
                            'Communication Services':  'Unknown',
                            'Real Estate':             'Unknown',
                            'Utilities':               'Unknown',
                        }
                        sector = sector_map.get(raw_sector, 'Unknown')
                    except Exception:
                        sector = 'Unknown'

                    atr_mult = 2.5 if is_venture else 2.0
                    stop  = curr - (atr * atr_mult)
                    risk  = curr - stop

                    # FIX: Position sizing — cap small accounts at 25% (was 50%) to limit
                    # gap-down exposure for overnight swing holds when you can't react intraday.
                    if eval_account < 500:
                        shares = int((eval_account * 0.25) / curr)
                    elif eval_account < 2500:
                        shares = int((eval_account * 0.20) / curr)
                    else:
                        shares = int((eval_account * 0.02) / risk)

                    shares = min(shares, int(eval_cash / curr))
                    if shares <= 0: continue

                    suggestions.append({
                        "ticker":        ticker,
                        "buy_price":     curr,
                        "stop_trigger":  round(stop, 2),
                        "stop_limit":    calculate_stop_gap(curr, stop),
                        "take_profit":   round(curr + (risk * 2.5), 2),
                        "shares":        shares,
                        "total_cost":    round(shares * curr, 2),
                        "setup":         "Venture Momentum" if is_venture else "Institutional Swing",
                        "sector":        sector,
                        "adx":           curr_adx,
                        # Earnings warning fields
                        "earnings_warning": has_earnings,
                        "earnings_days":    days_until,
                        "earnings_date":    earn_date_str,
                    })

            suggestions.sort(key=lambda x: x['adx'], reverse=True)
            # FIX: Return up to 8 results so you have options to cross-reference
            return suggestions[:8]

        except Exception as e:
            return [{"ticker": "ERROR", "setup": str(e)}]

    # --- ALIGNED PORTFOLIO AUDITOR (Fixed: portfolio_id filter, trim severity) ---
    def audit_portfolio(self, tickers, portfolio_id=None):
        if not tickers: return []
        try:
            conn = sqlite3.connect(DB_PATH)

            # FIX: Filter by portfolio_id so the same ticker in two portfolios
            # uses the correct buy date and avg cost for each portfolio independently.
            if portfolio_id is not None:
                raw_trades = conn.execute(
                    "SELECT ticker, type, shares, price FROM trades WHERE portfolio_id=?",
                    (portfolio_id,)
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

            if len(tickers) == 1:
                close_df = data[['Close']]
                high_df  = data[['High']]
                low_df   = data[['Low']]
            else:
                close_df = data['Close']
                high_df  = data['High']
                low_df   = data['Low']

            for ticker in tickers:
                if ticker not in close_df: continue
                c_s = close_df[ticker].dropna()
                h_s = high_df[ticker].dropna()
                l_s = low_df[ticker].dropna()
                if len(c_s) < 15: continue

                curr = float(c_s.iloc[-1])

                # FIX: Use portfolio_id-scoped query for buy date
                if portfolio_id is not None:
                    buy_date_row = conn.execute(
                        "SELECT MIN(date) FROM trades WHERE ticker=? AND type='Buy' AND portfolio_id=?",
                        (ticker, portfolio_id)
                    ).fetchone()
                else:
                    buy_date_row = conn.execute(
                        "SELECT MIN(date) FROM trades WHERE ticker=? AND type='Buy'",
                        (ticker,)
                    ).fetchone()

                buy_date_str = buy_date_row[0] if buy_date_row else None
                if buy_date_str:
                    buy_date = pd.to_datetime(buy_date_str).tz_localize(None)
                    valid_highs = h_s[h_s.index >= buy_date]
                    high_water_mark = float(valid_highs.max()) if not valid_highs.empty else curr
                else:
                    high_water_mark = curr

                h = holdings.get(ticker, {'shares': 0, 'avg_cost': curr})
                if h['shares'] <= 0: continue

                avg_c = h['avg_cost']
                is_venture = '.V' in ticker

                # ATR (14-day)
                tr = pd.concat([
                    (h_s - l_s),
                    (h_s - c_s.shift(1)).abs(),
                    (l_s - c_s.shift(1)).abs()
                ], axis=1).max(axis=1)
                atr = tr.rolling(14).mean().iloc[-1]

                atr_mult = 2.5 if is_venture else 2.0
                buffer = atr * atr_mult

                # Ratchet stop anchored to peak since purchase
                stop = round(high_water_mark - buffer, 2)

                # Break-even safety
                target_pct = 0.25 if is_venture else 0.15
                target_p = avg_c * (1 + target_pct)
                if high_water_mark >= target_p:
                    stop = max(stop, round(avg_c, 2))

                if stop >= curr:
                    stop = round(curr * 0.98, 2)

                # FIX: Distinguish trim severity — how far past target are we?
                upside_from_target = ((curr - target_p) / target_p * 100) if target_p > 0 else 0.0

                if curr <= stop:
                    status = "SELL"
                    reason = "Volatility Breach"
                    color  = "text-[#EF4444]"
                elif curr >= target_p:
                    if upside_from_target >= 15:
                        status = "TRIM"
                        reason = f"Target +{upside_from_target:.0f}% — trim aggressively"
                        color  = "text-[#F59E0B]"
                    else:
                        status = "TRIM"
                        reason = f"Target hit (+{upside_from_target:.0f}%) — consider partial exit"
                        color  = "text-[#22C55E]"
                else:
                    status = "HOLD"
                    reason = "Healthy"
                    color  = "text-[#22C55E]"

                results.append({
                    "ticker":        ticker,
                    "current_price": curr,
                    "stop_trigger":  stop,
                    "stop_limit":    calculate_stop_gap(curr, stop),
                    "status":        status,
                    "color":         color,
                    "reason":        reason,
                })

            conn.close()
            return results

        except Exception as e:
            return [{"ticker": "ERROR", "reason": str(e)}]

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
                    conn = sqlite3.connect(DB_PATH)
                    conn.execute("DELETE FROM trades")
                    conn.execute("DELETE FROM portfolios")
                    for p in df['Portfolio'].unique():
                        conn.execute("INSERT INTO portfolios (name) VALUES (?)", (p,))
                    for _, r in df.iterrows():
                        pid = conn.execute(
                            "SELECT id FROM portfolios WHERE name=?", (r['Portfolio'],)
                        ).fetchone()[0]
                        conn.execute(
                            "INSERT INTO trades (portfolio_id, ticker, type, shares, price, date) VALUES (?, ?, ?, ?, ?, ?)",
                            (pid, r['Ticker'], r['Type'], r['Shares'], r['Price'], r['Date'])
                        )
                    conn.commit()
                    conn.close()
                    # Clear all cache after import
                    self._dashboard_cache = {}
                    self.window.evaluate_js('loadPortfolios();')
                except: pass


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
