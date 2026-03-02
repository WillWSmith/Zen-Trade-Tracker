import customtkinter as ctk
import sqlite3
import datetime
import os
from tkinter import messagebox

# --- AppData Database Setup ---
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
    
    cursor.execute("SELECT COUNT(*) FROM portfolios")
    if cursor.fetchone()[0] == 0:
        cursor.executemany("INSERT INTO portfolios (name) VALUES (?)", [("LLM Account 1",), ("LLM Account 2",), ("LLM Account 3",)])
        date_now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sample_trades = [
            (1, 'BDIV.TO', 'Buy', 10, 15.50, date_now), (1, 'ECHI.TO', 'Buy', 5, 22.10, date_now),
            (2, 'REM.TO', 'Buy', 20, 10.05, date_now), (3, 'PIN.TO', 'Buy', 15, 18.20, date_now)
        ]
        cursor.executemany("INSERT INTO trades (portfolio_id, ticker, type, shares, price, date) VALUES (?, ?, ?, ?, ?, ?)", sample_trades)
        
    conn.commit()
    conn.close()

# --- Main App GUI ---
class TradeTrackerApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Zen Trade Tracker")
        self.geometry("950x700")
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("green")
        
        self.current_portfolio_id = 1
        self.setup_ui()
        self.load_portfolios()
        self.refresh_data()

    def setup_ui(self):
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        
        # Sidebar
        self.sidebar = ctk.CTkFrame(self, width=200, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.logo_label = ctk.CTkLabel(self.sidebar, text="Portfolios", font=ctk.CTkFont(size=20, weight="bold"))
        self.logo_label.grid(row=0, column=0, padx=20, pady=(20, 10))
        self.portfolio_menu = ctk.CTkOptionMenu(self.sidebar, command=self.change_portfolio)
        self.portfolio_menu.grid(row=1, column=0, padx=20, pady=10)
        
        # Main Content
        self.main_frame = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.main_frame.grid(row=0, column=1, sticky="nsew", padx=20, pady=20)
        self.main_frame.grid_columnconfigure(0, weight=1)
        self.main_frame.grid_rowconfigure(1, weight=1) # Holdings table weight
        self.main_frame.grid_rowconfigure(2, weight=1) # History table weight
        
        # Entry Form
        self.entry_frame = ctk.CTkFrame(self.main_frame)
        self.entry_frame.grid(row=0, column=0, sticky="ew", pady=(0, 20))
        self.ticker_entry = ctk.CTkEntry(self.entry_frame, placeholder_text="Ticker")
        self.ticker_entry.grid(row=0, column=0, padx=10, pady=10)
        self.type_menu = ctk.CTkOptionMenu(self.entry_frame, values=["Buy", "Sell"])
        self.type_menu.grid(row=0, column=1, padx=10, pady=10)
        self.shares_entry = ctk.CTkEntry(self.entry_frame, placeholder_text="Shares")
        self.shares_entry.grid(row=0, column=2, padx=10, pady=10)
        self.price_entry = ctk.CTkEntry(self.entry_frame, placeholder_text="Price")
        self.price_entry.grid(row=0, column=3, padx=10, pady=10)
        self.add_btn = ctk.CTkButton(self.entry_frame, text="Add Trade", command=self.add_trade)
        self.add_btn.grid(row=0, column=4, padx=10, pady=10)
        
        # Holdings Table
        ctk.CTkLabel(self.main_frame, text="Current Holdings & Book Value", font=ctk.CTkFont(size=16, weight="bold")).grid(row=1, column=0, sticky="w", pady=(0, 5))
        self.holdings_frame = ctk.CTkScrollableFrame(self.main_frame, height=200)
        self.holdings_frame.grid(row=2, column=0, sticky="nsew", pady=(0, 20))
        
        # History Table
        ctk.CTkLabel(self.main_frame, text="Trade History", font=ctk.CTkFont(size=16, weight="bold")).grid(row=3, column=0, sticky="w", pady=(0, 5))
        self.history_frame = ctk.CTkScrollableFrame(self.main_frame, height=200)
        self.history_frame.grid(row=4, column=0, sticky="nsew")

    def load_portfolios(self):
        conn = sqlite3.connect(DB_PATH)
        self.portfolios = {name: pid for pid, name in conn.execute("SELECT id, name FROM portfolios").fetchall()}
        conn.close()
        self.portfolio_menu.configure(values=list(self.portfolios.keys()))
        self.portfolio_menu.set(list(self.portfolios.keys())[0])

    def change_portfolio(self, choice):
        self.current_portfolio_id = self.portfolios[choice]
        self.refresh_data()

    def add_trade(self):
        try:
            shares = float(self.shares_entry.get())
            price = float(self.price_entry.get())
        except ValueError:
            messagebox.showerror("Error", "Shares and Price must be numbers.")
            return
            
        conn = sqlite3.connect(DB_PATH)
        conn.execute("INSERT INTO trades (portfolio_id, ticker, type, shares, price, date) VALUES (?, ?, ?, ?, ?, ?)",
                     (self.current_portfolio_id, self.ticker_entry.get().upper(), self.type_menu.get(), shares, price, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        conn.close()
        
        self.ticker_entry.delete(0, 'end'); self.shares_entry.delete(0, 'end'); self.price_entry.delete(0, 'end')
        self.refresh_data()

    def refresh_data(self):
        # Clear existing table rows
        for widget in self.holdings_frame.winfo_children() + self.history_frame.winfo_children():
            widget.destroy()

        conn = sqlite3.connect(DB_PATH)
        trades = conn.execute("SELECT ticker, type, shares, price, date FROM trades WHERE portfolio_id=?", (self.current_portfolio_id,)).fetchall()
        conn.close()
        
        # Setup Headers
        headers = ["Ticker", "Shares", "Book Value ($)"]
        for col, text in enumerate(headers):
            ctk.CTkLabel(self.holdings_frame, text=text, font=ctk.CTkFont(weight="bold")).grid(row=0, column=col, padx=20, pady=5, sticky="w")
            
        hist_headers = ["Date", "Type", "Ticker", "Shares", "Price ($)"]
        for col, text in enumerate(hist_headers):
            ctk.CTkLabel(self.history_frame, text=text, font=ctk.CTkFont(weight="bold")).grid(row=0, column=col, padx=20, pady=5, sticky="w")
            
        holdings = {}
        for ticker, t_type, shares, price, date in trades:
            if ticker not in holdings: holdings[ticker] = {'shares': 0, 'invested': 0.0}
            modifier = 1 if t_type == 'Buy' else -1
            holdings[ticker]['shares'] += shares * modifier
            holdings[ticker]['invested'] += (shares * price) * modifier

        # Populate Holdings
        row = 1
        for ticker, data in holdings.items():
            if data['shares'] > 0:
                ctk.CTkLabel(self.holdings_frame, text=ticker).grid(row=row, column=0, padx=20, pady=2, sticky="w")
                ctk.CTkLabel(self.holdings_frame, text=f"{data['shares']:.2f}").grid(row=row, column=1, padx=20, pady=2, sticky="w")
                ctk.CTkLabel(self.holdings_frame, text=f"{data['invested']:.2f}", text_color="#2ECC71").grid(row=row, column=2, padx=20, pady=2, sticky="w")
                row += 1

        # Populate History
        for row, (ticker, t_type, shares, price, date) in enumerate(reversed(trades), start=1):
            color = "#2ECC71" if t_type == "Buy" else "#E74C3C"
            ctk.CTkLabel(self.history_frame, text=date.split()[0]).grid(row=row, column=0, padx=20, pady=2, sticky="w")
            ctk.CTkLabel(self.history_frame, text=t_type, text_color=color).grid(row=row, column=1, padx=20, pady=2, sticky="w")
            ctk.CTkLabel(self.history_frame, text=ticker).grid(row=row, column=2, padx=20, pady=2, sticky="w")
            ctk.CTkLabel(self.history_frame, text=str(shares)).grid(row=row, column=3, padx=20, pady=2, sticky="w")
            ctk.CTkLabel(self.history_frame, text=f"{price:.2f}").grid(row=row, column=4, padx=20, pady=2, sticky="w")

if __name__ == "__main__":
    init_db()
    app = TradeTrackerApp()
    app.mainloop()
