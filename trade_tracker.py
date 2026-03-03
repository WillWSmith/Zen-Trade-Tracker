import sqlite3
import datetime
import os
import sys
import shutil
import yfinance as yf
import pandas as pd
import webview

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
        
        # Calculate current holdings and realized gains
        for ticker, t_type, shares, price, date in raw_trades:
            if ticker not in holdings_dict:
                holdings_dict[ticker] = {'shares': 0, 'avg_cost': 0.0}
            
            h = holdings_dict[ticker]
            if t_type == 'Buy':
                total_cost = (h['shares'] * h['avg_cost']) + (shares * price)
                h['shares'] += shares
                h['avg_cost'] = total_cost / h['shares']
            elif t_type == 'Sell':
                realized_gl += (price - h['avg_cost']) * shares
                h['shares'] -= shares
                if h['shares'] <= 0:
                    h['shares'] = 0
                    h['avg_cost'] = 0.0

        active_tickers = [t for t, d in holdings_dict.items() if d['shares'] > 0]
        
        total_market_value = 0.0
        total_book_value = 0.0
        holdings_array = []
        
        for ticker in active_tickers:
            data = holdings_dict[ticker]
            shares = data['shares']
            avg_cost = data['avg_cost']
            
            try: current_price = yf.Ticker(ticker).fast_info.last_price
            except: current_price = avg_cost
            
            book_val = shares * avg_cost
            market_val = shares * current_price
            unreal_dlr = market_val - book_val
            
            total_book_value += book_val
            total_market_value += market_val
            
            holdings_array.append({
                "ticker": ticker,
                "shares": shares,
                "avg_cost": avg_cost,
                "current_price": current_price,
                "unreal_dlr": unreal_dlr
            })

        unreal_total_dlr = total_market_value - total_book_value
        unreal_total_pct = (unreal_total_dlr / total_book_value * 100) if total_book_value > 0 else 0

        # --- TRUE DAILY LEDGER CHART MATH ---
        chart_dates = []
        chart_values = []
        
        if raw_trades and first_trade_query and first_trade_query[0]:
            first_trade_date = datetime.datetime.strptime(first_trade_query[0], "%Y-%m-%d %H:%M:%S")
            now = datetime.datetime.now()
            
            # Determine Requested Start Date
            if timeframe == "1M":
                requested_start = now - datetime.timedelta(days=30)
            elif timeframe == "1Y":
                requested_start = now - datetime.timedelta(days=365)
            else:
                requested_start = first_trade_date
                
            # CLAMP: Never show data from before the portfolio actually existed
            actual_start_date = max(requested_start, first_trade_date)
            
            if (now - actual_start_date).days < 1:
                actual_start_date = now - datetime.timedelta(days=2)
                
            start_str = actual_start_date.strftime("%Y-%m-%d")

            # 1. Build a timeline of all trades
            all_tickers_ever_held = list(set([t[0] for t in raw_trades]))
            trades_df = pd.DataFrame(raw_trades, columns=['ticker', 'type', 'shares', 'price', 'date'])
            trades_df['date'] = pd.to_datetime(trades_df['date']).dt.tz_localize(None).dt.floor('D')
            
            # Modifier: Buys are positive, Sells are negative
            trades_df['share_change'] = trades_df.apply(lambda row: row['shares'] if row['type'] == 'Buy' else -row['shares'], axis=1)

            # Sum daily changes per ticker
            daily_changes = trades_df.groupby(['date', 'ticker'])['share_change'].sum().unstack(fill_value=0)
            
            # 2. Fetch Historical Prices for ALL tickers ever traded
            hist_prices = pd.DataFrame()
            for ticker in all_tickers_ever_held:
                try:
                    df = yf.Ticker(ticker).history(start=start_str)
                    if not df.empty: 
                        df.index = df.index.tz_localize(None).floor('D') 
                        hist_prices[ticker] = df['Close']
                except: pass
                
            if not hist_prices.empty and not daily_changes.empty:
                # 3. Calculate true daily share balances from the very beginning of time
                full_date_range = pd.date_range(start=daily_changes.index.min(), end=now.floor('D'))
                daily_balances = daily_changes.reindex(full_date_range, fill_value=0).cumsum()
                
                # Align the share balances strictly to the market dates we pulled
                market_dates = hist_prices.index
                daily_balances_aligned = daily_balances.reindex(market_dates).ffill() # Forward fill any gaps
                
                # 4. Multiply accurate daily shares * actual daily prices
                common_tickers = list(set(daily_balances_aligned.columns) & set(hist_prices.columns))
                daily_equity = (daily_balances_aligned[common_tickers] * hist_prices[common_tickers]).sum(axis=1)
                
                chart_dates = [d.strftime('%b %d, %Y') for d in daily_equity.index]
                chart_values = daily_equity.values.tolist()

        history_array = [{"date": d, "type": t, "ticker": tick, "shares": s, "price": p} for tick, t, s, p, d in reversed(raw_trades)]

        return {
            "total_market": total_market_value,
            "unreal_dlr": unreal_total_dlr,
            "unreal_pct": unreal_total_pct,
            "realized_gl": realized_gl,
            "holdings": holdings_array,
            "history": history_array,
            "chart_dates": chart_dates,
            "chart_values": chart_values
        }

    def export_db(self):
        if self.window:
            dest_path = self.window.create_file_dialog(webview.SAVE_DIALOG, directory='', save_filename='ZenTradeBackup.db')
            if dest_path: shutil.copy2(DB_PATH, dest_path[0])

    def import_db(self):
        if self.window:
            src_path = self.window.create_file_dialog(webview.OPEN_DIALOG)
            if src_path:
                shutil.copy2(src_path[0], DB_PATH)
                self.window.evaluate_js('loadPortfolios()')

def get_entrypoint():
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, 'gui', 'index.html')
    return os.path.join(os.path.dirname(__file__), 'gui', 'index.html')

if __name__ == '__main__':
    init_db()
    
    try:
        import pyi_splash
        pyi_splash.close()
    except ImportError:
        pass

    api = BackendAPI()

    window = webview.create_window(
        'Zen Trade Tracker - v1.0.0', 
        url=get_entrypoint(),
        js_api=api,
        width=1200, height=850, 
        background_color='#000000',
        resizable=True
    )
    
    api.window = window
    webview.start()
