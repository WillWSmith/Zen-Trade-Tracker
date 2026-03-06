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

    # --- NIGHT OWL SCANNER ALGORITHM (Institutional Grade) ---
    def run_swing_scanner(self, cash_available):
        try:
            # 1. Position Sizing Logic
            eval_cash = max(cash_available, 5.0) 
            
            if eval_cash < 100:
                max_position_size = eval_cash
            else:
                max_position_size = eval_cash * 0.20
                
            min_shares = 10  
            max_allowed_price = max_position_size / min_shares
            
            # 2. Dynamic TradingView Scrape (TSX.V)
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
            
            if eval_cash < 2000:
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
                    
                if eval_cash < 10000:
                    full_universe = dynamic_tsx + tsx_v_staples
                else:
                    full_universe = dynamic_tsx + tsx_v_staples[:15]

            full_universe = list(set(full_universe))
            if len(full_universe) > 350:
                full_universe = full_universe[:350]

            # 3. Download 1 FULL YEAR of data to calculate 200-Day SMA and 52-Wk High
            data = yf.download(full_universe, period="1y", progress=False)
            if 'Close' not in data or 'Volume' not in data: return []
                
            close_data = data['Close']
            volume_data = data['Volume']
            
            suggestions = []
            
            for ticker in full_universe:
                if ticker not in close_data.columns: continue
                    
                c_series = close_data[ticker].dropna()
                v_series = volume_data[ticker].dropna()
                
                # Must have at least 200 trading days to confirm a true macro uptrend
                if len(c_series) < 200: continue
                
                current_price = float(c_series.iloc[-1])
                
                # PRICE & SPREAD CHECK
                if current_price > max_allowed_price or current_price < 0.15: continue 
                
                # LIQUIDITY CHECK
                avg_vol = float(v_series.tail(20).mean())
                today_vol = float(v_series.iloc[-1])
                is_venture = '.V' in ticker
                min_adv = 250000 if is_venture else 100000
                
                if avg_vol < min_adv: continue
                
                # ELITE MATH (1-Year Context)
                sma_200 = float(c_series.tail(200).mean())
                sma_50 = float(c_series.tail(50).mean())
                sma_10 = float(c_series.tail(10).mean())
                recent_low = float(c_series.tail(10).min())
                high_52wk = float(c_series.max())
                
                # MOMENTUM PROXIMITY FILTER: Current price must be within 25% of the 52-week high
                if current_price < (high_52wk * 0.75): continue
                
                # THE "FORTRESS" RULE: 50 SMA must be higher than 200 SMA (Golden Cross)
                if sma_50 > sma_200:
                    # THE "STRATOSPHERE" RULE: Must be above 50 SMA, but NO MORE than 20% above it
                    if current_price > sma_50 and current_price < (sma_50 * 1.20):
                        
                        # SHORT TERM PULLBACK RULE
                        if current_price < sma_10:
                            
                            stop_trigger = min(sma_50, recent_low) * 0.98 
                            stop_limit = stop_trigger * 0.98 
                            
                            risk = current_price - stop_trigger
                            if risk <= 0: continue
                            
                            take_profit = current_price + (risk * 2.5)
                            shares = int(max_position_size / current_price)
                            
                            if shares >= min_shares:
                                
                                # SMART TAGGING LOGIC
                                if current_price >= (high_52wk * 0.90):
                                    setup_tag = "🔥 52-Wk High Pullback"
                                elif today_vol > (avg_vol * 1.5):
                                    setup_tag = "🌊 High Volume Drop"
                                else:
                                    setup_tag = "🛡️ Golden Cross Pullback"
                                
                                suggestions.append({
                                    "ticker": ticker,
                                    "buy_price": current_price,
                                    "stop_trigger": stop_trigger,
                                    "stop_limit": stop_limit,
                                    "take_profit": take_profit,
                                    "shares": shares,
                                    "total_cost": shares * current_price,
                                    "setup": setup_tag
                                })
                                
            # Sort by tightest Risk %
            suggestions.sort(key=lambda x: (x['buy_price'] - x['stop_trigger']) / x['buy_price'])
            return suggestions[:3] 
            
        except Exception as e:
            return [{"ticker": "ERROR", "buy_price": 0, "stop_trigger": 0, "stop_limit": 0, "take_profit": 0, "shares": 0, "total_cost": 0, "setup": str(e)}]

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
                    for p in portfolios:
                        conn.execute("INSERT INTO portfolios (name) VALUES (?)", (p,))
                    
                    for index, row in df.iterrows():
                        pid = conn.execute("SELECT id FROM portfolios WHERE name=?", (row['Portfolio'],)).fetchone()[0]
                        conn.execute("INSERT INTO trades (portfolio_id, ticker, type, shares, price, date) VALUES (?, ?, ?, ?, ?, ?)",
                                     (pid, row['Ticker'], row['Type'], row['Shares'], row['Price'], row['Date']))
                    conn.commit()
                    conn.close()
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
        'Zen Trade Tracker - v1.0.0', url=get_entrypoint(), js_api=api,
        width=1350, height=850, background_color='#121214', resizable=True
    )
    api.window = window
    webview.start()
