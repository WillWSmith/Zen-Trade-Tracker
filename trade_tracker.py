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
        total_cash = 0.0
        
        # Calculate current holdings, cash balances, and realized gains
        for ticker, t_type, shares, price, date in raw_trades:
            if t_type == 'Deposit':
                total_cash += shares
            elif t_type == 'Withdraw':
                total_cash -= shares
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

        total_account_value = total_market_value + total_cash
        unreal_total_dlr = total_market_value - total_book_value
        unreal_total_pct = (unreal_total_dlr / total_book_value * 100) if total_book_value > 0 else 0

        # --- TRUE DAILY LEDGER (CASH + EQUITY) ---
        chart_dates = []
        chart_values = []
        
        if raw_trades and first_trade_query and first_trade_query[0]:
            first_trade_date = datetime.datetime.strptime(first_trade_query[0], "%Y-%m-%d %H:%M:%S")
            now = datetime.datetime.now()
            
            # Timeframe clamping
            if timeframe == "1M": requested_start = now - datetime.timedelta(days=30)
            elif timeframe == "1Y": requested_start = now - datetime.timedelta(days=365)
            else: requested_start = first_trade_date
                
            actual_start_date = max(requested_start, first_trade_date)
            if (now - actual_start_date).days < 1: actual_start_date = now - datetime.timedelta(days=2)
            start_str = actual_start_date.strftime("%Y-%m-%d")

            trades_df = pd.DataFrame(raw_trades, columns=['ticker', 'type', 'shares', 'price', 'date'])
            trades_df['date'] = pd.to_datetime(trades_df['date']).dt.tz_localize(None).dt.floor('D')

            # Calculate changes in shares
            def get_share_change(row):
                if row['type'] == 'Buy': return row['shares']
                elif row['type'] == 'Sell': return -row['shares']
                return 0
            trades_df['share_change'] = trades_df.apply(get_share_change, axis=1)

            # Calculate changes in cash balances
            def get_cash_change(row):
                if row['type'] == 'Buy': return -(row['shares'] * row['price'])
                elif row['type'] == 'Sell': return (row['shares'] * row['price'])
                elif row['type'] == 'Deposit': return row['shares']
                elif row['type'] == 'Withdraw': return -row['shares']
                return 0
            trades_df['cash_change'] = trades_df.apply(get_cash_change, axis=1)

            # Build full timeline from first ever action to today
            full_date_range = pd.date_range(start=trades_df['date'].min(), end=now.floor('D'))
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
                            df.index = df.index.tz_localize(None).floor('D')
                            hist_prices[ticker] = df['Close']
                    except: pass
                    
                if not hist_prices.empty:
                    daily_balances = daily_changes.reindex(full_date_range, fill_value=0).cumsum()
                    market_dates = hist_prices.index
                    
                    # Align share balances and cash balances to the days the market was actually open
                    daily_balances_aligned = daily_balances.reindex(market_dates).ffill()
                    daily_cash_aligned = daily_cash_balances.reindex(market_dates).ffill()
                    
                    common_tickers = list(set(daily_balances_aligned.columns) & set(hist_prices.columns))
                    daily_equity = (daily_balances_aligned[common_tickers] * hist_prices[common_tickers]).sum(axis=1)
                    
                    # Total Account = Market Equity + Cash
                    daily_total_account = daily_equity + daily_cash_aligned
                    daily_total_account = daily_total_account.loc[daily_total_account.index >= actual_start_date]
                    
                    chart_dates = [d.strftime('%b %d, %Y') for d in daily_total_account.index]
                    chart_values = daily_total_account.values.tolist()
                else:
                    # Fallback if Yahoo Finance is down
                    daily_cash_limited = daily_cash_balances.loc[daily_cash_balances.index >= actual_start_date]
                    chart_dates = [d.strftime('%b %d, %Y') for d in daily_cash_limited.index]
                    chart_values = daily_cash_limited.values.tolist()
            else:
                # If they only have cash deposited and no stock trades yet
                daily_cash_limited = daily_cash_balances.loc[daily_cash_balances.index >= actual_start_date]
                chart_dates = [d.strftime('%b %d, %Y') for d in daily_cash_limited.index]
                chart_values = daily_cash_limited.values.tolist()

        history_array = [{"date": d, "type": t, "ticker": tick, "shares": s, "price": p} for tick, t, s, p, d in reversed(raw_trades)]

        return {
            "total_account": total_account_value,
            "total_cash": total_cash,
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
