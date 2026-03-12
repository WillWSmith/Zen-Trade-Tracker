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

class BackendAPI:
    def __init__(self):
        self.window = None
        self.is_maximized = False

    def minimize(self):
        if self.window: self.window.minimize()

    def toggle_maximize(self):
        if self.window:
            if self.is_maximized:
                self.window.restore()
                self.is_maximized = False
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
                "date": date,
                "type": t_type,
                "ticker": ticker,
                "shares": float(shares),
                "price": float(price),
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
            
            unreal_dlr = market_val - book_val
            today_dlr = market_val - prev_market_val
            
            total_book_value += book_val
            total_market_value += market_val
            total_prev_market_value += prev_market_val
            total_today_dlr += today_dlr
            
            holdings_array.append({
                "ticker": ticker,
                "shares": float(shares),
                "avg_cost": float(avg_cost),
                "current_price": float(current_price),
                "unreal_dlr": float(unreal_dlr),
                "market_val": float(market_val) 
            })

        total_account_value = total_market_value + total_cash
        unreal_total_dlr = total_market_value - total_book_value
        unreal_total_pct = (unreal_total_dlr / total_book_value * 100) if total_book_value > 0 else 0.0
        realized_pct = (realized_gl / net_deposits * 100) if net_deposits > 0 else 0.0
        today_pct = (total_today_dlr / total_prev_market_value * 100) if total_prev_market_value > 0 else 0.0

        for h in holdings_array:
            h["allocation"] = (h["market_val"] / total_account_value * 100) if total_account_value > 0 else 0.0

        chart_dates = []
        chart_values = []
        
        if raw_trades and first_trade_query and first_trade_query[0]:
            first_trade_date = datetime.datetime.strptime(first_trade_query[0], "%Y-%m-%d %H:%M:%S")
            now = datetime.datetime.now()
            
            if timeframe == "1M": requested_start = now - datetime.timedelta(days=30)
            elif timeframe == "1Y": requested_start = now - datetime.timedelta(days=365)
            else: requested_start = first_trade_date
                
            actual_start_date = max(requested_start, first_trade_date)
            if (now - actual_start_date).days < 1: actual_start_date = now - datetime.timedelta(days=2)
            start_str = actual_start_date.strftime("%Y-%m-%d")

            trades_df = pd.DataFrame(raw_trades, columns=['ticker', 'type', 'shares', 'price', 'date'])
            trades_df['date'] = pd.to_datetime(trades_df['date']).dt.floor('D')

            def get_share_change(row):
                if row['type'] == 'Buy': return row['shares']
                elif row['type'] == 'Sell': return -row['shares']
                return 0
            trades_df['share_change'] = trades_df.apply(get_share_change, axis=1)

            def get_cash_change(row):
                if row['type'] == 'Buy': return -(row['shares'] * row['price'])
                elif row['type'] == 'Sell': return (row['shares'] * row['price'])
                elif row['type'] == 'Deposit': return row['shares']
                elif row['type'] == 'Withdraw': return -row['shares']
                elif row['type'] == 'Dividend': return (row['shares'] * row['price'])
                return 0
            trades_df['cash_change'] = trades_df.apply(get_cash_change, axis=1)

            full_date_range = pd.date_range(start=trades_df['date'].min(), end=pd.Timestamp(now).floor('D'))
            daily_cash_changes = trades_df.groupby('date')['cash_change'].sum()
            daily_cash_balances = daily_cash_changes.reindex(full_date_range, fill_value=0).cumsum()

            stock_trades = trades_df[trades_df['type'].isin(['Buy', 'Sell'])]
            
            if not stock_trades.empty:
                daily_changes = stock_trades.groupby(['date', 'ticker'])['share_change'].sum().unstack(fill_value=0)
                all_tickers = daily_changes.columns.tolist()
                
                hist_prices = pd.DataFrame()
                for ticker in all_tickers:
                    try:
                        df = yf.Ticker(ticker).history(start=start_str)
                        if not df.empty:
                            if df.index.tz is not None: df.index = df.index.tz_localize(None)
                            df.index = df.index.floor('D')
                            hist_prices[ticker] = df['Close']
                    except: pass
                    
                if not hist_prices.empty:
                    daily_balances = daily_changes.reindex(full_date_range, fill_value=0).cumsum()
                    market_dates = hist_prices.index
                    
                    daily_balances_aligned = daily_balances.reindex(market_dates).ffill().fillna(0)
                    daily_cash_aligned = daily_cash_balances.reindex(market_dates).ffill().fillna(0)
                    hist_prices = hist_prices.ffill().bfill().fillna(0)
                    
                    common_tickers = list(set(daily_balances_aligned.columns) & set(hist_prices.columns))
                    daily_equity = (daily_balances_aligned[common_tickers] * hist_prices[common_tickers]).sum(axis=1)
                    
                    daily_total_account = daily_equity + daily_cash_aligned
                    daily_total_account = daily_total_account.loc[daily_total_account.index >= actual_start_date]
                    
                    chart_dates = [d.strftime('%b %d, %Y') for d in daily_total_account.index]
                    chart_values = daily_total_account.values.tolist()
                else:
                    daily_cash_limited = daily_cash_balances.loc[daily_cash_balances.index >= actual_start_date]
                    chart_dates = [d.strftime('%b %d, %Y') for d in daily_cash_limited.index]
                    chart_values = daily_cash_limited.values.tolist()
            else:
                daily_cash_limited = daily_cash_balances.loc[daily_cash_balances.index >= actual_start_date]
                chart_dates = [d.strftime('%b %d, %Y') for d in daily_cash_limited.index]
                chart_values = daily_cash_limited.values.tolist()

        chart_values = [0 if pd.isna(x) else float(x) for x in chart_values]

        return {
            "total_account": float(total_account_value),
            "total_cash": float(total_cash),
            "today_dlr": float(total_today_dlr),
            "today_pct": float(today_pct),
            "total_market": float(total_market_value),
            "unreal_dlr": float(unreal_total_dlr),
            "unreal_pct": float(unreal_total_pct),
            "realized_gl": float(realized_gl),
            "realized_pct": float(realized_pct),
            "holdings": holdings_array,
            "history": history_enriched,
            "unique_tickers": unique_tickers,
            "chart_dates": chart_dates,
            "chart_values": chart_values
        }

    # --- ZEN SCANNER ALGORITHM (ADX & ATR Upgraded) ---
    def run_swing_scanner(self, cash_available):
        try:
            eval_cash = max(cash_available, 5.0) 
            
            if eval_cash < 500: max_position_size = eval_cash * 1.0    
            elif eval_cash < 2500: max_position_size = eval_cash * 0.50   
            elif eval_cash < 10000: max_position_size = eval_cash * 0.33   
            else: max_position_size = eval_cash * 0.20   
                
            tsx_v_staples = [
                'HIVE.V', 'BITF.V', 'NILI.V', 'PMN.V', 'SGN.V', 'LI.V', 'EU.V', 'CRE.V', 
                'ISO.V', 'AFM.V', 'VLI.V', 'GGD.V', 'RECO.V', 'SLI.V', 'FL.V', 'NGD.V'
            ]
            
            tv_url = "https://scanner.tradingview.com/canada/scan"
            try:
                v_payload = {
                    "filter": [{"left": "exchange", "operation": "equal", "right": "TSXV"}],
                    "options": {"lang": "en"},
                    "markets": ["canada"],
                    "symbols": {"query": {"types": []}, "tickers": []},
                    "columns": ["name", "volume"],
                    "sort": {"sortBy": "volume", "sortOrder": "desc"},
                    "range": [0, 100] 
                }
                v_resp = requests.post(tv_url, json=v_payload, timeout=5)
                if v_resp.status_code == 200:
                    dynamic_v = [f"{item['d'][0].replace('.', '-')}.V" for item in v_resp.json().get("data", []) if item.get("d")]
                    tsx_v_staples = list(set(tsx_v_staples + dynamic_v))
            except: pass

            full_universe = []
            if eval_cash < 500:
                full_universe = tsx_v_staples + ['BTE.TO', 'CPG.TO', 'ATH.TO', 'CVE.TO', 'CJ.TO']
            else:
                dynamic_tsx = ['SHOP.TO', 'RY.TO', 'TD.TO', 'ENB.TO', 'CNR.TO', 'CP.TO', 'BMO.TO', 'SU.TO', 'CSU.TO']
                try:
                    t_payload = {
                        "filter": [{"left": "exchange", "operation": "equal", "right": "TSX"}],
                        "options": {"lang": "en"},
                        "markets": ["canada"],
                        "symbols": {"query": {"types": []}, "tickers": []},
                        "columns": ["name", "volume"],
                        "sort": {"sortBy": "volume", "sortOrder": "desc"},
                        "range": [0, 150] 
                    }
                    t_resp = requests.post(tv_url, json=t_payload, timeout=5)
                    if t_resp.status_code == 200:
                        dynamic_tsx = [f"{item['d'][0].replace('.', '-')}.TO" for item in t_resp.json().get("data", []) if item.get("d")]
                except: pass
                    
                if eval_cash < 5000: full_universe = dynamic_tsx + tsx_v_staples
                else: full_universe = dynamic_tsx + tsx_v_staples[:15]

            full_universe = list(set(full_universe))[:350]

            # We need High, Low, Close for ADX/ATR math
            data = yf.download(full_universe, period="1y", progress=False)
            if 'Close' not in data or 'Volume' not in data: return []
                
            close_data = data['Close']
            high_data = data['High']
            low_data = data['Low']
            volume_data = data['Volume']
            
            suggestions = []
            
            for ticker in full_universe:
                if ticker not in close_data.columns: continue
                    
                c_series = close_data[ticker].dropna()
                h_series = high_data[ticker].dropna()
                l_series = low_data[ticker].dropna()
                v_series = volume_data[ticker].dropna()
                
                if len(c_series) < 200: continue
                
                current_price = float(c_series.iloc[-1])
                is_venture = '.V' in ticker
                
                min_shares = 10 if is_venture else 1
                max_allowed_price = max_position_size / min_shares
                if current_price > max_allowed_price or current_price < 0.15: continue 
                
                avg_vol = float(v_series.tail(20).mean())
                today_vol = float(v_series.iloc[-1])
                
                # 1. DOLLAR VOLUME LIQUIDITY GUARD
                dollar_volume = avg_vol * current_price
                if dollar_volume < 100000: continue
                
                # 2. ATR & ADX CALCULATION (Pandas Math)
                tr1 = h_series - l_series
                tr2 = (h_series - c_series.shift(1)).abs()
                tr3 = (l_series - c_series.shift(1)).abs()
                tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
                
                plus_dm = h_series.diff()
                minus_dm = -l_series.diff()
                plus_dm[(plus_dm < 0) | (plus_dm < minus_dm)] = 0
                minus_dm[(minus_dm < 0) | (minus_dm < plus_dm)] = 0
                
                atr_14 = tr.rolling(14).mean()
                atr_sum = tr.rolling(14).sum()
                
                plus_di = 100 * (plus_dm.rolling(14).sum() / atr_sum)
                minus_di = 100 * (minus_dm.rolling(14).sum() / atr_sum)
                dx = (plus_di - minus_di).abs() / (plus_di + minus_di).abs() * 100
                adx = dx.rolling(14).mean()
                
                current_adx = float(adx.iloc[-1])
                current_atr = float(atr_14.iloc[-1])
                
                # 3. MOMENTUM FILTER (ADX > 25)
                if pd.isna(current_adx) or current_adx < 25: continue
                
                sma_200 = float(c_series.tail(200).mean())
                sma_50 = float(c_series.tail(50).mean())
                sma_10 = float(c_series.tail(10).mean())
                high_52wk = float(h_series.tail(252).max())
                
                if current_price < (high_52wk * 0.75): continue
                
                if sma_50 > sma_200:
                    if current_price > sma_50 and current_price < (sma_50 * 1.20):
                        if current_price < sma_10:
                            
                            # 4. VOLATILITY STOP WITH DYNAMIC CAPS
                            cap = 0.15 if current_price < 1.00 else 0.10
                            raw_risk_pct = (current_atr * 2) / current_price
                            dynamic_buffer = min(raw_risk_pct, cap)
                            
                            stop_trigger = sma_50 * (1.0 - dynamic_buffer)
                            stop_limit = stop_trigger * 0.98 
                            
                            risk = current_price - stop_trigger
                            if risk <= 0: continue
                            
                            take_profit = current_price + (risk * 2.5)
                            shares = int(max_position_size / current_price)
                            
                            if shares >= min_shares:
                                try:
                                    sector_raw = yf.Ticker(ticker).info.get('sector', 'Unknown')
                                    if sector_raw == 'Basic Materials': sector = 'Materials'
                                    elif sector_raw == 'Financial Services': sector = 'Financials'
                                    elif sector_raw == 'Consumer Cyclical': sector = 'Cyclical'
                                    elif sector_raw == 'Communication Services': sector = 'Comm Services'
                                    else: sector = sector_raw
                                except: sector = 'Unknown'

                                if current_price >= (high_52wk * 0.90): setup_tag = "52-Wk High Pullback"
                                elif today_vol > (avg_vol * 1.5): setup_tag = "High Vol Drop"
                                else: setup_tag = "Golden Cross Pullback"
                                
                                suggestions.append({
                                    "ticker": ticker,
                                    "buy_price": current_price,
                                    "stop_trigger": stop_trigger,
                                    "stop_limit": stop_limit,
                                    "take_profit": take_profit,
                                    "shares": shares,
                                    "total_cost": shares * current_price,
                                    "setup": setup_tag,
                                    "sector": sector,
                                    "adx": current_adx # Sort by momentum
                                })
                                
            # SORT BY PURE MOMENTUM INSTEAD OF TIGHTEST STOP
            suggestions.sort(key=lambda x: x['adx'], reverse=True)
            return suggestions[:3] 
            
        except Exception as e:
            return [{"ticker": "ERROR", "buy_price": 0, "stop_trigger": 0, "stop_limit": 0, "take_profit": 0, "shares": 0, "total_cost": 0, "setup": str(e), "sector": "", "adx": 0}]

    # --- PORTFOLIO AUDITOR ALGORITHM (High-Water Mark Upgraded) ---
    def audit_portfolio(self, tickers):
        if not tickers: return []
        try:
            data = yf.download(tickers, period="1y", progress=False)
            close_data = pd.DataFrame()
            high_data = pd.DataFrame()
            
            if len(tickers) == 1:
                if 'Close' in data: close_data[tickers[0]] = data['Close']
                if 'High' in data: high_data[tickers[0]] = data['High']
            else:
                if 'Close' in data: close_data = data['Close']
                if 'High' in data: high_data = data['High']
                    
            if close_data.empty: return []

            results = []
            for ticker in tickers:
                if ticker not in close_data.columns or ticker not in high_data.columns: continue
                
                c_series = close_data[ticker].dropna()
                h_series = high_data[ticker].dropna()
                if len(c_series) < 50: continue
                
                current_price = float(c_series.iloc[-1])
                sma_50 = float(c_series.tail(50).mean())
                ema_8 = float(c_series.ewm(span=8, adjust=False).mean().iloc[-1])
                peak_price = float(h_series.tail(20).max()) # High-Water mark of last month
                
                # HIGH WATER TRAILING STOP LOGIC
                stop_trigger = max(sma_50, ema_8, peak_price * 0.90)
                stop_limit = stop_trigger * 0.98 
                
                if current_price <= stop_trigger:
                    status = "SELL"
                    color = "text-[#EF4444]" 
                    reason = "Trailing Stop Breached"
                elif current_price > (sma_50 * 1.25):
                    status = "TRIM"
                    color = "text-[#EAB308]" 
                    reason = "Overextended (>25% Above 50 SMA)"
                else:
                    status = "HOLD"
                    color = "text-[#22C55E]" 
                    reason = "Trend Healthy"
                    
                results.append({
                    "ticker": ticker,
                    "current_price": current_price,
                    "stop_trigger": stop_trigger,
                    "stop_limit": stop_limit,
                    "status": status,
                    "color": color,
                    "reason": reason
                })
                
            sort_order = {"SELL": 0, "TRIM": 1, "HOLD": 2}
            results.sort(key=lambda x: sort_order.get(x["status"], 3))
            return results
        except Exception as e:
            return [{"ticker": "ERROR", "reason": str(e)}]
    
    def export_csv(self):
        if self.window:
            dest_path = self.window.create_file_dialog(webview.SAVE_DIALOG, directory='', save_filename='ZenTrades.csv')
            if dest_path:
                conn = sqlite3.connect(DB_PATH)
                trades = conn.execute("SELECT portfolios.name, ticker, type, shares, price, date FROM trades JOIN portfolios ON trades.portfolio_id = portfolios.id").fetchall()
                conn.close()
                with open(dest_path[0], 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow(['Portfolio', 'Ticker', 'Type', 'Shares', 'Price', 'Date'])
                    writer.writerows(trades)
                self.window.evaluate_js('alert("CSV Exported Successfully!")')

    def import_csv(self):
        if self.window:
            src_path = self.window.create_file_dialog(webview.OPEN_DIALOG, file_types=('CSV Files (*.csv)',))
            if src_path:
                try:
                    df = pd.read_csv(src_path[0])
                    conn = sqlite3.connect(DB_PATH)
                    conn.execute("DELETE FROM trades")
                    conn.execute("DELETE FROM portfolios")
                    portfolios = df['Portfolio'].unique()
                    for p in portfolios: conn.execute("INSERT INTO portfolios (name) VALUES (?)", (p,))
                    for index, row in df.iterrows():
                        pid = conn.execute("SELECT id FROM portfolios WHERE name=?", (row['Portfolio'],)).fetchone()[0]
                        conn.execute("INSERT INTO trades (portfolio_id, ticker, type, shares, price, date) VALUES (?, ?, ?, ?, ?, ?)",
                                     (pid, row['Ticker'], row['Type'], row['Shares'], row['Price'], row['Date']))
                    conn.commit(); conn.close()
                    self.window.evaluate_js('loadPortfolios(); alert("CSV Imported Successfully!");')
                except Exception as e:
                    self.window.evaluate_js(f'alert("Import Error: Make sure headers are Portfolio, Ticker, Type, Shares, Price, Date");')

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
        width=1280, height=760, 
        background_color='#0a0a0c', 
        resizable=True,
        frameless=True
    )
    api.window = window
    webview.start()
