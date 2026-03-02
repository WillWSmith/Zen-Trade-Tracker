import customtkinter as ctk
import sqlite3
import datetime
from tkinter import messagebox

# --- Database Setup ---
def init_db():
    conn = sqlite3.connect('trades_local.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS portfolios (
            id INTEGER PRIMARY KEY,
            name TEXT UNIQUE
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY,
            portfolio_id INTEGER,
            ticker TEXT,
            type TEXT,
            shares REAL,
            price REAL,
            date TEXT,
            FOREIGN KEY(portfolio_id) REFERENCES portfolios(id)
        )
    ''')
    
    # Insert default portfolios if none exist
    cursor.execute("SELECT COUNT(*) FROM portfolios")
    if cursor.fetchone()[0] == 0:
        default_portfolios = [("LLM Account 1",), ("LLM Account 2",), ("LLM Account 3",)]
        cursor.executemany("INSERT INTO portfolios (name) VALUES (?)", default_portfolios)
        
        # Add some sample mock trades 
        date_now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sample_trades = [
            (1, 'BDIV.TO', 'Buy', 10, 15.50, date_now),
            (1, 'ECHI.TO', 'Buy', 5, 22.10, date_now),
            (2, 'REM.TO', 'Buy', 20, 10.05, date_now),
            (3, 'PIN.TO', 'Buy', 15, 18.20, date_now)
        ]
        cursor.executemany("INSERT INTO trades (portfolio_id, ticker, type, shares, price, date) VALUES (?, ?, ?, ?, ?, ?)", sample_trades)
        
    conn.commit()
    conn.close()

# --- Main App GUI ---
class TradeTrackerApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        self.title("Zen Trade Tracker")
        self.geometry("900x600")
        
        # Set dark theme and green accents
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("green")
        
        self.current_portfolio_id = 1
        
        self.setup_ui()
        self.load_portfolios()
        self.refresh_data()

    def setup_ui(self):
        # Grid layout: 1 row, 2 columns (Sidebar and Main Content)
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        
        # --- Sidebar ---
        self.sidebar = ctk.CTkFrame(self, width=200, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_rowconfigure(2, weight=1)
        
        self.logo_label = ctk.CTkLabel(self.sidebar, text="Portfolios", font=ctk.CTkFont(size=20, weight="bold"))
        self.logo_label.grid(row=0, column=0, padx=20, pady=(20, 10))
        
        self.portfolio_menu = ctk.CTkOptionMenu(self.sidebar, command=self.change_portfolio)
        self.portfolio_menu.grid(row=1, column=0, padx=20, pady=10)
        
        # --- Main Content ---
        self.main_frame = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.main_frame.grid(row=0, column=1, sticky="nsew", padx=20, pady=20)
        self.main_frame.grid_columnconfigure(0, weight=1)
        self.main_frame.grid_rowconfigure(1, weight=1)
        
        # Entry Form
        self.entry_frame = ctk.CTkFrame(self.main_frame)
        self.entry_frame.grid(row=0, column=0, sticky="ew", pady=(0, 20))
        
        self.ticker_entry = ctk.CTkEntry(self.entry_frame, placeholder_text="Ticker (e.g. XEG.TO)")
        self.ticker_entry.grid(row=0, column=0, padx=10, pady=10)
        
        self.type_menu = ctk.CTkOptionMenu(self.entry_frame, values=["Buy", "Sell"])
        self.type_menu.grid(row=0, column=1, padx=10, pady=10)
        
        self.shares_entry = ctk.CTkEntry(self.entry_frame, placeholder_text="Shares")
        self.shares_entry.grid(row=0, column=2, padx=10, pady=10)
        
        self.price_entry = ctk.CTkEntry(self.entry_frame, placeholder_text="Price")
        self.price_entry.grid(row=0, column=3, padx=10, pady=10)
        
        self.add_btn = ctk.CTkButton(self.entry_frame, text="Add Trade", command=self.add_trade)
        self.add_btn.grid(row=0, column=4, padx=10, pady=10)
        
        # Data Display
        self.data_display = ctk.CTkTextbox(self.main_frame, font=ctk.CTkFont(family="Consolas", size=14))
        self.data_display.grid(row=1, column=0, sticky="nsew")

    def load_portfolios(self):
        conn = sqlite3.connect('trades_local.db')
        cursor = conn.cursor()
        cursor.execute("SELECT id, name FROM portfolios")
        self.portfolios = {name: pid for pid, name in cursor.fetchall()}
        conn.close()
        
        self.portfolio_menu.configure(values=list(self.portfolios.keys()))
        self.portfolio_menu.set(list(self.portfolios.keys())[0])

    def change_portfolio(self, choice):
        self.current_portfolio_id = self.portfolios[choice]
        self.refresh_data()

    def add_trade(self):
        ticker = self.ticker_entry.get().upper()
        trade_type = self.type_menu.get()
        
        try:
            shares = float(self.shares_entry.get())
            price = float(self.price_entry.get())
        except ValueError:
            messagebox.showerror("Input Error", "Shares and Price must be numbers.")
            return
            
        date_now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        conn = sqlite3.connect('trades_local.db')
        cursor = conn.cursor()
        cursor.execute("INSERT INTO trades (portfolio_id, ticker, type, shares, price, date) VALUES (?, ?, ?, ?, ?, ?)",
                       (self.current_portfolio_id, ticker, trade_type, shares, price, date_now))
        conn.commit()
        conn.close()
        
        self.ticker_entry.delete(0, 'end')
        self.shares_entry.delete(0, 'end')
        self.price_entry.delete(0, 'end')
        self.refresh_data()

    def refresh_data(self):
        self.data_display.delete("1.0", "end")
        conn = sqlite3.connect('trades_local.db')
        cursor = conn.cursor()
        
        # Fetch Holdings (Simplified calculation)
        cursor.execute("SELECT ticker, type, shares, price FROM trades WHERE portfolio_id=?", (self.current_portfolio_id,))
        trades = cursor.fetchall()
        conn.close()
        
        holdings = {}
        total_invested = 0.0
        
        for ticker, t_type, shares, price in trades:
            if ticker not in holdings:
                holdings[ticker] = {'shares': 0, 'invested': 0.0}
            
            if t_type == 'Buy':
                holdings[ticker]['shares'] += shares
                holdings[ticker]['invested'] += shares * price
                total_invested += shares * price
            elif t_type == 'Sell':
                holdings[ticker]['shares'] -= shares
                holdings[ticker]['invested'] -= shares * price
                total_invested -= shares * price
        
        self.data_display.insert("end", f"--- CURRENT HOLDINGS ---\n")
        self.data_display.insert("end", f"{'TICKER':<10} | {'SHARES':<10} | {'BOOK VALUE':<10}\n")
        self.data_display.insert("end", "-"*40 + "\n")
        
        for ticker, data in holdings.items():
            if data['shares'] > 0:
                self.data_display.insert("end", f"{ticker:<10} | {data['shares']:<10.2f} | ${data['invested']:<10.2f}\n")
        
        self.data_display.insert("end", f"\nTotal Book Value: ${total_invested:.2f}\n\n")
        
        self.data_display.insert("end", f"--- TRADE HISTORY ---\n")
        for ticker, t_type, shares, price in reversed(trades): # Show newest first
            self.data_display.insert("end", f"{t_type} {shares} shrs of {ticker} @ ${price:.2f}\n")

if __name__ == "__main__":
    init_db()
    app = TradeTrackerApp()
    app.mainloop()
