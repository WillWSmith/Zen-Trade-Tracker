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

class BackendAPI:
    def __init__(self):
        self.window = None
        self.is_maximized = False

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

    def add_trade(self, pid, ticker, type, shares, price):
        conn = sqlite3.connect(DB_PATH)
        conn.execute("INSERT INTO trades (portfolio_id, ticker, type, shares, price, date) VALUES (?, ?, ?, ?, ?, ?)",
                     (pid, ticker, type, shares, price, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit(); conn.close()

    def get_dashboard_data(self, pid, timeframe="All Time"):
        conn = sqlite3.connect(DB_PATH)
        raw_trades = conn.execute("SELECT ticker, type, shares, price, date FROM trades WHERE portfolio_id=? ORDER BY date ASC", (pid,)).fetchall()
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
            now = datetime.datetime.now()
            if timeframe == "1M": requested_start = now - datetime.timedelta(days=30)
            elif timeframe == "1Y": requested_start = now - datetime.timedelta(days=365)
            else: requested_start = first_trade_date
            actual_start_date = max(requested_start, first_trade_date)
            start_str = actual_start_date.strftime("%Y-%m-%d")

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

            full_range = pd.date_range(start=trades_df['date'].min(), end=pd.Timestamp(now).floor('D'), freq='D')
            daily_cash = trades_df.groupby('date')['cash_change'].sum().reindex(full_range, fill_value=0).cumsum()
            
            # Initialize daily equity with zeros on the full range
            daily_equity = pd.Series(0.0, index=full_range)

            stock_trades = trades_df[trades_df['type'].isin(['Buy', 'Sell'])]
            if not stock_trades.empty:
                daily_changes = stock_trades.groupby(['date', 'ticker'])['share_change'].sum().unstack(fill_value=0)
                # Reindex changes to full range immediately to ensure we have all days
                balances = daily_changes.reindex(full_range, fill_value=0).cumsum().fillna(0)
                
                tickers_to_fetch = list(daily_changes.columns)
                if tickers_to_fetch:
                    try:
                        # Fetch all prices at once for efficiency
                        price_data = yf.download(tickers_to_fetch, start=full_range.min().strftime('%Y-%m-%d'), progress=False)['Close']
                        if isinstance(price_data, pd.Series): # single ticker
                            price_data = price_data.to_frame(name=tickers_to_fetch[0])
                        
                        if not price_data.empty:
                            if price_data.index.tz: price_data.index = price_data.index.tz_localize(None)
                            # Reindex price data to full_range and forward fill
                            hist_prices = price_data.reindex(full_range).ffill().bfill().fillna(0)
                            
                            # Calculate equity: Balances * Prices
                            daily_equity = (balances * hist_prices).sum(axis=1)
                    except:
                        pass
            
            # Combine Cash + Equity for the final account value
            total_acc = daily_cash + daily_equity
            
            # Filter by timeframe
            total_acc = total_acc[total_acc.index >= actual_start_date]
            
            chart_dates = [d.strftime('%b %d, %Y') for d in total_acc.index]
            chart_values = [float(x) for x in total_acc.values]

        return {
            "total_account": float(total_account_value), "total_cash": float(total_cash),
            "today_dlr": float(total_today_dlr), "today_pct": float(today_pct),
            "total_market": float(total_market_value), "unreal_dlr": float(unreal_total_dlr),
            "unreal_pct": float(unreal_total_pct), "realized_gl": float(realized_gl),
            "realized_pct": (realized_gl / net_deposits * 100) if net_deposits > 0 else 0.0,
            "holdings": holdings_array, "history": history_enriched, "unique_tickers": unique_tickers,
            "chart_dates": chart_dates, "chart_values": [0 if pd.isna(x) else float(x) for x in chart_values]
        }

    # --- ZEN MASTER SCANNER (Refined Volatility & Multi-Exchange) ---
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
                    full_universe += [f"{item['d'][0].replace('.', '-')}{suffix}" for item in resp.json().get("data", []) if item.get("d")]

            data = yf.download(list(set(full_universe)), period="1y", progress=False)
            if 'Close' not in data: return []
            close_data, high_data, low_data, vol_data = data['Close'], data['High'], data['Low'], data['Volume']
            suggestions = []
            
            for ticker in close_data.columns:
                c_s, h_s, l_s, v_s = close_data[ticker].dropna(), high_data[ticker].dropna(), low_data[ticker].dropna(), vol_data[ticker].dropna()
                if len(c_s) < 200: continue
                
                curr = float(c_s.iloc[-1])
                avg_v = float(v_s.tail(20).mean())
                is_venture = '.V' in ticker
                
                # 1. LIQUIDITY & VOLUME SPIKE
                vol_mult = 2.0 if is_venture else 1.5
                if (avg_v * curr) < 250000 or (float(v_s.iloc[-1]) < (avg_v * vol_mult)): continue 
                
                # 2. VOLATILITY GUARD (ATR 14)
                tr = pd.concat([(h_s-l_s), (h_s-c_s.shift(1)).abs(), (l_s-c_s.shift(1)).abs()], axis=1).max(axis=1)
                atr = tr.rolling(14).mean().iloc[-1]
                if (atr / curr) > 0.08: continue # Cap entry at 8% daily ATR to avoid extreme junk

                # 3. RSI & ADX
                plus_di = 100 * ((h_s.diff().clip(lower=0)).rolling(14).sum() / tr.rolling(14).sum())
                minus_di = 100 * ((-l_s.diff().clip(lower=0)).rolling(14).sum() / tr.rolling(14).sum())
                adx = ((plus_di - minus_di).abs() / (plus_di + minus_di).abs() * 100).rolling(14).mean()
                curr_adx = float(adx.iloc[-1])
                
                delta = c_s.diff()
                rsi = 100 - (100 / (1 + (delta.clip(lower=0).ewm(com=13).mean() / (-1 * delta.clip(upper=0).ewm(com=13).mean()))))
                curr_rsi = float(rsi.iloc[-1])
                
                if curr_adx < 25 or curr_rsi < 35 or curr_rsi > 75: continue

                # 4. TREND CONFIRMATION
                h52 = float(h_s.tail(252).max())
                sma50, sma200 = float(c_s.tail(50).mean()), float(c_s.tail(200).mean())
                
                if is_venture:
                    if curr < (h52 * 0.85) or curr < sma50: continue 
                else:
                    if curr < (h52 * 0.75) or curr < sma200: continue

                if curr < (sma50 * 1.25) and curr < float(c_s.tail(10).mean()):
                    # Use Aligned Vol-Adjusted Logic
                    atr_mult = 2.5 if is_venture else 2.0
                    stop = curr - (atr * atr_mult)
                    risk = curr - stop
                    
                    if eval_account < 500: shares = int((eval_account * 0.50) / curr)
                    elif eval_account < 2500: shares = int((eval_account * 0.25) / curr)
                    else: shares = int((eval_account * 0.02) / risk)
                    
                    shares = min(shares, int(eval_cash / curr))
                    if shares <= 0: continue
                    
                    suggestions.append({
                        "ticker": ticker, "buy_price": curr, "stop_trigger": round(stop, 2), 
                        "stop_limit": calculate_stop_gap(curr, stop), "take_profit": round(curr + (risk * 2.5), 2),
                        "shares": shares, "total_cost": round(shares * curr, 2),
                        "setup": "Venture Momentum" if is_venture else "Institutional Swing", 
                        "sector": "Market Leader", "adx": curr_adx
                    })
                                
            suggestions.sort(key=lambda x: x['adx'], reverse=True)
            return suggestions[:3] 
        except Exception as e: return [{"ticker": "ERROR", "setup": str(e)}]

    # --- ALIGNED PORTFOLIO AUDITOR (Trailing ATR Logic) ---
    def audit_portfolio(self, tickers):
        if not tickers: return []
        try:
            conn = sqlite3.connect(DB_PATH)
            raw_trades = conn.execute("SELECT ticker, type, shares, price FROM trades").fetchall()
            conn.close()
            holdings = {}
            for t, ty, s, p in raw_trades:
                if t not in holdings: holdings[t] = {'shares': 0, 'avg_cost': 0.0}
                if ty == 'Buy': 
                    cost = (holdings[t]['shares'] * holdings[t]['avg_cost']) + (s * p)
                    holdings[t]['shares'] += s
                    holdings[t]['avg_cost'] = cost / holdings[t]['shares']
                elif ty == 'Sell': holdings[t]['shares'] -= s

            # Download OHLC for ATR calculation
            data = yf.download(tickers, period="1y", progress=False)
            results = []
            
            if len(tickers) == 1:
                close_df, high_df, low_df = data[['Close']], data[['High']], data[['Low']]
            else:
                close_df, high_df, low_df = data['Close'], data['High'], data['Low']

            conn = sqlite3.connect(DB_PATH)
            for ticker in tickers:
                if ticker not in close_df: continue
                c_s, h_s, l_s = close_df[ticker].dropna(), high_df[ticker].dropna(), low_df[ticker].dropna()
                if len(c_s) < 15: continue
                
                curr = float(c_s.iloc[-1])
                
                # 1. Find the earliest 'Buy' date for this ticker to set the High-Water Mark anchor
                buy_date_str = conn.execute("SELECT MIN(date) FROM trades WHERE ticker=? AND type='Buy'", (ticker,)).fetchone()[0]
                if buy_date_str:
                    buy_date = pd.to_datetime(buy_date_str).tz_localize(None)
                    # Filter history from buy date to now
                    valid_highs = h_s[h_s.index >= buy_date]
                    high_water_mark = float(valid_highs.max()) if not valid_highs.empty else curr
                else:
                    high_water_mark = curr

                h = holdings.get(ticker, {'shares': 0, 'avg_cost': curr})
                if h['shares'] <= 0: continue
                
                avg_c = h['avg_cost']
                is_venture = '.V' in ticker
                
                # 2. ATR Calculation (14-day smoothed)
                tr = pd.concat([(h_s-l_s), (h_s-c_s.shift(1)).abs(), (l_s-c_s.shift(1)).abs()], axis=1).max(axis=1)
                atr = tr.rolling(14).mean().iloc[-1]
                
                atr_mult = 2.5 if is_venture else 2.0
                buffer = atr * atr_mult
                
                # 3. Apply the Ratchet: Stop is anchored to the peak reached SINCE purchase
                stop = round(high_water_mark - buffer, 2)
                
                # 4. Break-even Safety Logic
                target_pct = 0.25 if is_venture else 0.15
                target_p = avg_c * (1 + target_pct)
                if high_water_mark >= target_p: 
                    stop = max(stop, round(avg_c, 2))
                
                if stop >= curr: stop = round(curr * 0.98, 2)
                
                status = "SELL" if curr <= stop else ("TRIM" if curr >= target_p else "HOLD")
                results.append({
                    "ticker": ticker, "current_price": curr, 
                    "stop_trigger": stop, "stop_limit": calculate_stop_gap(curr, stop), 
                    "status": status, "color": "text-[#EF4444]" if status == "SELL" else "text-[#22C55E]", 
                    "reason": "Volatility Breach" if status == "SELL" else ("Target Hit" if status == "TRIM" else "Healthy")
                })
            return results
        except Exception as e: return [{"ticker": "ERROR", "reason": str(e)}]

    def export_csv(self):
        if self.window:
            path = self.window.create_file_dialog(webview.SAVE_DIALOG, save_filename='ZenTrades.csv')
            if path:
                conn = sqlite3.connect(DB_PATH)
                trades = conn.execute("SELECT portfolios.name, ticker, type, shares, price, date FROM trades JOIN portfolios ON trades.portfolio_id = portfolios.id").fetchall()
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
                    conn.execute("DELETE FROM trades"); conn.execute("DELETE FROM portfolios")
                    for p in df['Portfolio'].unique(): conn.execute("INSERT INTO portfolios (name) VALUES (?)", (p,))
                    for _, r in df.iterrows():
                        pid = conn.execute("SELECT id FROM portfolios WHERE name=?", (r['Portfolio'],)).fetchone()[0]
                        conn.execute("INSERT INTO trades (portfolio_id, ticker, type, shares, price, date) VALUES (?, ?, ?, ?, ?, ?)", (pid, r['Ticker'], r['Type'], r['Shares'], r['Price'], r['Date']))
                    conn.commit(); conn.close(); self.window.evaluate_js('loadPortfolios();')
                except: pass

def get_entrypoint():
    if hasattr(sys, '_MEIPASS'): return os.path.join(sys._MEIPASS, 'gui', 'index.html')
    return os.path.join(os.path.dirname(__file__), 'gui', 'index.html')

if __name__ == '__main__':
    init_db()
    try: import pyi_splash; pyi_splash.close()
    except ImportError: pass
    api = BackendAPI()
    window = webview.create_window('Zen Portfolios', url=get_entrypoint(), js_api=api, width=1280, height=760, background_color='#0a0a0c', resizable=True, frameless=True)
    api.window = window
    webview.start()
