import customtkinter as ctk
import sqlite3
import datetime
import os
import sys
import threading
import shutil
import yfinance as yf
from tkinter import messagebox
from customtkinter import filedialog
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

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

class TradeTrackerApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Zen Trade Tracker")
        self.center_window(1150, 850)
        
        try:
            self.iconbitmap(resource_path('icon.ico'))
        except:
            pass 
            
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("green")
        
        self.current_portfolio_id = None
        self.portfolios = {}
        self.live_prices = {}
        
        self.setup_ui()
        self.load_portfolios()

    def center_window(self, width, height):
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        x = int((screen_width / 2) - (width / 2))
        y = int((screen_height / 2) - (height / 2))
        self.geometry(f'{width}x{height}+{x}+{y}')

    def setup_ui(self):
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        
        # --- Sidebar ---
        self.sidebar = ctk.CTkFrame(self, width=220, corner_radius=0, fg_color="#1a1a1a")
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        
        ctk.CTkLabel(self.sidebar, text="Zen Portfolios", font=ctk.CTkFont(size=22, weight="bold")).grid(row=0, column=0, padx=20, pady=(30, 10))
        self.portfolio_menu = ctk.CTkOptionMenu(self.sidebar, command=self.change_portfolio, corner_radius=8)
        self.portfolio_menu.grid(row=1, column=0, padx=20, pady=10)
        
        self.btn_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        self.btn_frame.grid(row=2, column=0, pady=10)
        ctk.CTkButton(self.btn_frame, text="Add", width=60, corner_radius=8, command=self.add_portfolio).grid(row=0, column=0, padx=5)
        ctk.CTkButton(self.btn_frame, text="Edit", width=60, corner_radius=8, command=self.edit_portfolio).grid(row=0, column=1, padx=5)
        ctk.CTkButton(self.btn_frame, text="Del", width=60, corner_radius=8, fg_color="#E74C3C", hover_color="#C0392B", command=self.delete_portfolio).grid(row=0, column=2, padx=5)
        
        ctk.CTkLabel(self.sidebar, text="Log New Trade", font=ctk.CTkFont(size=16, weight="bold")).grid(row=3, column=0, pady=(30, 5))
        self.ticker_combo = ctk.CTkComboBox(self.sidebar, values=["Type or Select..."], corner_radius=8)
        self.ticker_combo.grid(row=4, column=0, padx=20, pady=5)
        self.type_menu = ctk.CTkOptionMenu(self.sidebar, values=["Buy", "Sell"], corner_radius=8)
        self.type_menu.grid(row=5, column=0, padx=20, pady=5)
        self.shares_entry = ctk.CTkEntry(self.sidebar, placeholder_text="Shares", corner_radius=8)
        self.shares_entry.grid(row=6, column=0, padx=20, pady=5)
        self.price_entry = ctk.CTkEntry(self.sidebar, placeholder_text="Price", corner_radius=8)
        self.price_entry.grid(row=7, column=0, padx=20, pady=5)
        ctk.CTkButton(self.sidebar, text="Submit Trade", corner_radius=8, font=ctk.CTkFont(weight="bold"), command=self.add_trade).grid(row=8, column=0, padx=20, pady=15)

        # --- Main Content Area ---
        self.main_frame = ctk.CTkFrame(self, corner_radius=0, fg_color="#0d0d0d")
        self.main_frame.grid(row=0, column=1, sticky="nsew", padx=20, pady=20)
        self.main_frame.grid_columnconfigure((0, 1, 2), weight=1)
        self.main_frame.grid_rowconfigure(3, weight=1) 
        
        self.top_bar = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.top_bar.grid(row=0, column=0, columnspan=3, sticky="e", pady=(0, 10))
        ctk.CTkButton(self.top_bar, text="Import DB", width=90, corner_radius=8, fg_color="#34495E", hover_color="#2C3E50", command=self.import_db).pack(side="left", padx=5)
        ctk.CTkButton(self.top_bar, text="Export DB", width=90, corner_radius=8, fg_color="#34495E", hover_color="#2C3E50", command=self.export_db).pack(side="left", padx=5)
        ctk.CTkButton(self.top_bar, text="Refresh Market", width=120, corner_radius=8, font=ctk.CTkFont(weight="bold"), fg_color="#27AE60", hover_color="#2ECC71", command=self.refresh_data).pack(side="left", padx=(15, 5))

        self.card_val = self.create_summary_card(self.main_frame, "Total Market Value", "$0.00", 1, 0)
        self.card_unreal = self.create_summary_card(self.main_frame, "Unrealized G/L (Holdings)", "$0.00 (0.0%)", 1, 1)
        self.card_real = self.create_summary_card(self.main_frame, "Realized G/L (Recognized)", "$0.00", 1, 2)
        
        self.graph_frame = ctk.CTkFrame(self.main_frame, height=220, corner_radius=15, fg_color="#1a1a1a")
        self.graph_frame.grid(row=2, column=0, columnspan=3, sticky="nsew", pady=(20, 20))
        self.graph_frame.pack_propagate(False)
        self.graph_canvas = None
        
        self.tables_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.tables_frame.grid(row=3, column=0, columnspan=3, sticky="nsew")
        self.tables_frame.grid_columnconfigure((0, 1), weight=1)
        self.tables_frame.grid_rowconfigure(1, weight=1)
        
        ctk.CTkLabel(self.tables_frame, text="Current Holdings", font=ctk.CTkFont(size=16, weight="bold")).grid(row=0, column=0, sticky="w", pady=(0, 5))
        ctk.CTkLabel(self.tables_frame, text="Trade History", font=ctk.CTkFont(size=16, weight="bold")).grid(row=0, column=1, sticky="w", padx=(20,0), pady=(0, 5))
        
        self.holdings_frame = ctk.CTkScrollableFrame(self.tables_frame, corner_radius=15, fg_color="#1a1a1a")
        self.holdings_frame.grid(row=1, column=0, sticky="nsew", padx=(0, 10))
        self.history_frame = ctk.CTkScrollableFrame(self.tables_frame, corner_radius=15, fg_color="#1a1a1a")
        self.history_frame.grid(row=1, column=1, sticky="nsew", padx=(10, 0))

    def create_summary_card(self, parent, title, default_val, row, col):
        card = ctk.CTkFrame(parent, corner_radius=15, fg_color="#1a1a1a", height=90)
        card.grid(row=row, column=col, sticky="nsew", padx=10)
        card.grid_propagate(False)
        card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(card, text=title, font=ctk.CTkFont(size=13), text_color="#a0a0a0").grid(row=0, column=0, pady=(15, 2))
        val_label = ctk.CTkLabel(card, text=default_val, font=ctk.CTkFont(size=26, weight="bold"))
        val_label.grid(row=1, column=0)
        return val_label

    def export_db(self):
        dest_path = filedialog.asksaveasfilename(defaultextension=".db", filetypes=[("SQLite Database", "*.db")], initialfile="ZenTradeBackup.db", title="Export Database")
        if dest_path:
            try:
                shutil.copy2(DB_PATH, dest_path)
                messagebox.showinfo("Success", f"Database successfully exported!")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to export database:\n{e}")

    def import_db(self):
        if not messagebox.askyesno("Warning", "Importing a database will completely overwrite your current trades and portfolios. Do you wish to continue?"): return
        src_path = filedialog.askopenfilename(filetypes=[("SQLite Database", "*.db")], title="Select Database to Import")
        if src_path:
            try:
                shutil.copy2(src_path, DB_PATH)
                messagebox.showinfo("Success", "Database successfully imported!")
                self.load_portfolios() 
            except Exception as e:
                messagebox.showerror("Error", f"Failed to import database:\n{e}")

    def load_portfolios(self, select_name=None):
        conn = sqlite3.connect(DB_PATH)
        self.portfolios = {name: pid for pid, name in conn.execute("SELECT id, name FROM portfolios").fetchall()}
        conn.close()
        
        if not self.portfolios:
            self.portfolio_menu.configure(values=["No Portfolios"]); self.portfolio_menu.set("No Portfolios"); self.current_portfolio_id = None
            self.refresh_data()
            return
            
        self.portfolio_menu.configure(values=list(self.portfolios.keys()))
        target = select_name if select_name in self.portfolios else list(self.portfolios.keys())[0]
        self.portfolio_menu.set(target)
        self.current_portfolio_id = self.portfolios[target]
        self.refresh_data()

    def change_portfolio(self, choice):
        if choice in self.portfolios:
            self.current_portfolio_id = self.portfolios[choice]
            self.refresh_data()

    def add_portfolio(self):
        dialog = ctk.CTkInputDialog(text="Enter new portfolio name:", title="Add Portfolio")
        name = dialog.get_input()
        if name:
            try:
                conn = sqlite3.connect(DB_PATH)
                conn.execute("INSERT INTO portfolios (name) VALUES (?)", (name.strip(),))
                conn.commit(); conn.close()
                self.load_portfolios(select_name=name.strip())
            except sqlite3.IntegrityError:
                messagebox.showerror("Error", "Portfolio exists.")

    def edit_portfolio(self):
        if not self.current_portfolio_id: return
        current_name = self.portfolio_menu.get()
        dialog = ctk.CTkInputDialog(text=f"Rename '{current_name}' to:", title="Edit Portfolio")
        new_name = dialog.get_input()
        if new_name and new_name.strip() != current_name:
            try:
                conn = sqlite3.connect(DB_PATH)
                conn.execute("UPDATE portfolios SET name=? WHERE id=?", (new_name.strip(), self.current_portfolio_id))
                conn.commit(); conn.close()
                self.load_portfolios(select_name=new_name.strip())
            except:
                messagebox.showerror("Error", "Portfolio exists.")

    def delete_portfolio(self):
        if not self.current_portfolio_id: return
        if messagebox.askyesno("Confirm Delete", "Permanently delete this portfolio?"):
            conn = sqlite3.connect(DB_PATH)
            conn.execute("DELETE FROM trades WHERE portfolio_id=?", (self.current_portfolio_id,))
            conn.execute("DELETE FROM portfolios WHERE id=?", (self.current_portfolio_id,))
            conn.commit(); conn.close()
            self.load_portfolios()

    def add_trade(self):
        if not self.current_portfolio_id: return
        ticker = self.ticker_combo.get().strip().upper()
        if not ticker or ticker == "TYPE OR SELECT...": return
        try:
            shares = float(self.shares_entry.get())
            price = float(self.price_entry.get())
        except ValueError:
            messagebox.showerror("Error", "Numbers only for shares/price.")
            return
            
        conn = sqlite3.connect(DB_PATH)
        conn.execute("INSERT INTO trades (portfolio_id, ticker, type, shares, price, date) VALUES (?, ?, ?, ?, ?, ?)",
                     (self.current_portfolio_id, ticker, self.type_menu.get(), shares, price, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit(); conn.close()
        
        self.shares_entry.delete(0, 'end'); self.price_entry.delete(0, 'end')
        self.refresh_data()

    def fetch_live_prices(self, tickers):
        for ticker in tickers:
            try:
                stock = yf.Ticker(ticker)
                self.live_prices[ticker] = stock.fast_info.last_price
            except:
                pass 
        self.after(0, self.update_ui_with_data)

    def refresh_data(self):
        self.card_val.configure(text="Loading Data...")
        self.card_unreal.configure(text="Fetching Prices...")
        threading.Thread(target=self.process_trade_math, daemon=True).start()

    def process_trade_math(self):
        if not self.current_portfolio_id:
            self.after(0, self.update_ui_with_data)
            return
            
        conn = sqlite3.connect(DB_PATH)
        self.trades = conn.execute("SELECT ticker, type, shares, price, date FROM trades WHERE portfolio_id=? ORDER BY date ASC", (self.current_portfolio_id,)).fetchall()
        conn.close()

        self.holdings = {}
        self.realized_gl = 0.0
        
        for ticker, t_type, shares, price, date in self.trades:
            if ticker not in self.holdings:
                self.holdings[ticker] = {'shares': 0, 'avg_cost': 0.0}
            
            h = self.holdings[ticker]
            if t_type == 'Buy':
                total_cost = (h['shares'] * h['avg_cost']) + (shares * price)
                h['shares'] += shares
                h['avg_cost'] = total_cost / h['shares']
            elif t_type == 'Sell':
                self.realized_gl += (price - h['avg_cost']) * shares
                h['shares'] -= shares
                if h['shares'] <= 0:
                    h['shares'] = 0
                    h['avg_cost'] = 0.0

        active_tickers = [tick for tick, data in self.holdings.items() if data['shares'] > 0]
        self.fetch_live_prices(active_tickers)

    def update_ui_with_data(self):
        for widget in self.holdings_frame.winfo_children() + self.history_frame.winfo_children(): widget.destroy()

        if not self.current_portfolio_id:
            self.card_val.configure(text="$0.00"); self.card_unreal.configure(text="$0.00 (0.0%)"); self.card_real.configure(text="$0.00")
            self.ticker_combo.configure(values=["No Portfolio Selected"]); self.ticker_combo.set("No Portfolio Selected")
            if self.graph_canvas: self.graph_canvas.get_tk_widget().destroy()
            return

        total_market_value = 0.0
        total_book_value = 0.0
        chart_labels = []
        chart_sizes = []

        # --- Draw Holdings Table ---
        header_frame_h = ctk.CTkFrame(self.holdings_frame, fg_color="transparent")
        header_frame_h.pack(fill="x", pady=(0, 5))
        for col, text in enumerate(["Ticker", "Shares", "Avg Cost", "Mkt Price", "Unrealized"]):
            ctk.CTkLabel(header_frame_h, text=text, font=ctk.CTkFont(weight="bold"), text_color="#a0a0a0", width=80, anchor="w").pack(side="left", padx=10)
        
        active_holdings = {k:v for k,v in self.holdings.items() if v['shares'] > 0}
        for index, (ticker, data) in enumerate(active_holdings.items()):
            bg_color = "#1a1a1a" if index % 2 == 0 else "#242424" # Zebra Striping
            row_frame = ctk.CTkFrame(self.holdings_frame, fg_color=bg_color, corner_radius=5)
            row_frame.pack(fill="x", pady=2)
            
            shares, avg_cost = data['shares'], data['avg_cost']
            book_val = shares * avg_cost
            current_price = self.live_prices.get(ticker, avg_cost) 
            market_val = shares * current_price
            unreal_dlr = market_val - book_val
            unreal_pct = (unreal_dlr / book_val * 100) if book_val > 0 else 0
            
            total_book_value += book_val
            total_market_value += market_val
            chart_labels.append(ticker)
            chart_sizes.append(market_val)

            color = "#2ECC71" if unreal_dlr >= 0 else "#E74C3C"
            
            ctk.CTkLabel(row_frame, text=ticker, font=ctk.CTkFont(weight="bold"), width=80, anchor="w").pack(side="left", padx=10, pady=5)
            ctk.CTkLabel(row_frame, text=f"{shares:,.2f}", width=80, anchor="w").pack(side="left", padx=10, pady=5)
            ctk.CTkLabel(row_frame, text=f"${avg_cost:,.2f}", width=80, anchor="w").pack(side="left", padx=10, pady=5)
            ctk.CTkLabel(row_frame, text=f"${current_price:,.2f}", width=80, anchor="w").pack(side="left", padx=10, pady=5)
            ctk.CTkLabel(row_frame, text=f"${unreal_dlr:,.2f} ({unreal_pct:.1f}%)", text_color=color, width=80, anchor="w").pack(side="left", padx=10, pady=5)

        # --- Draw History Table ---
        header_frame_hist = ctk.CTkFrame(self.history_frame, fg_color="transparent")
        header_frame_hist.pack(fill="x", pady=(0, 5))
        for col, text in enumerate(["Date", "Type", "Ticker", "Shares", "Price"]):
            ctk.CTkLabel(header_frame_hist, text=text, font=ctk.CTkFont(weight="bold"), text_color="#a0a0a0", width=75, anchor="w").pack(side="left", padx=10)

        for index, (ticker, t_type, shares, price, date) in enumerate(reversed(self.trades)):
            bg_color = "#1a1a1a" if index % 2 == 0 else "#242424" # Zebra Striping
            row_frame = ctk.CTkFrame(self.history_frame, fg_color=bg_color, corner_radius=5)
            row_frame.pack(fill="x", pady=2)
            
            t_color = "#2ECC71" if t_type == "Buy" else "#E74C3C"
            ctk.CTkLabel(row_frame, text=date.split()[0], width=75, anchor="w").pack(side="left", padx=10, pady=5)
            ctk.CTkLabel(row_frame, text=t_type, text_color=t_color, width=75, font=ctk.CTkFont(weight="bold"), anchor="w").pack(side="left", padx=10, pady=5)
            ctk.CTkLabel(row_frame, text=ticker, width=75, anchor="w").pack(side="left", padx=10, pady=5)
            ctk.CTkLabel(row_frame, text=f"{shares:,.2f}", width=75, anchor="w").pack(side="left", padx=10, pady=5)
            ctk.CTkLabel(row_frame, text=f"${price:,.2f}", width=75, anchor="w").pack(side="left", padx=10, pady=5)

        # Update Top Level Metrics
        total_unreal_dlr = total_market_value - total_book_value
        total_unreal_pct = (total_unreal_dlr / total_book_value * 100) if total_book_value > 0 else 0
        
        self.card_val.configure(text=f"${total_market_value:,.2f}")
        u_color = "#2ECC71" if total_unreal_dlr >= 0 else "#E74C3C"
        self.card_unreal.configure(text=f"${total_unreal_dlr:,.2f} ({total_unreal_pct:,.1f}%)", text_color=u_color)
        r_color = "#2ECC71" if self.realized_gl >= 0 else "#E74C3C"
        self.card_real.configure(text=f"${self.realized_gl:,.2f}", text_color=r_color)
        
        active_tickers = [tick for tick, data in self.holdings.items() if data['shares'] > 0]
        self.ticker_combo.configure(values=active_tickers if active_tickers else ["Type new ticker..."])
        self.ticker_combo.set(active_tickers[0] if active_tickers else "Type new ticker...")

        self.draw_chart(chart_labels, chart_sizes)

    def draw_chart(self, labels, sizes):
        if self.graph_canvas:
            self.graph_canvas.get_tk_widget().destroy()
            
        if not sizes or sum(sizes) == 0:
            ctk.CTkLabel(self.graph_frame, text="Log trades to see your portfolio allocation chart.", text_color="#a0a0a0").place(relx=0.5, rely=0.5, anchor="center")
            return
            
        fig, ax = plt.subplots(figsize=(8, 2.2), facecolor='#1a1a1a')
        ax.set_facecolor('#1a1a1a')
        
        colors = ['#2ECC71', '#27AE60', '#1ABC9C', '#16A085', '#F1C40F', '#F39C12', '#E67E22']
        wedges, texts, autotexts = ax.pie(sizes, labels=labels, autopct='%1.1f%%', startangle=90, 
                                          colors=colors, textprops={'color':"w", 'fontsize': 10, 'weight': 'bold'})
        
        for w in wedges: w.set_edgecolor('#1a1a1a')
        plt.tight_layout()
        
        self.graph_canvas = FigureCanvasTkAgg(fig, master=self.graph_frame)
        self.graph_canvas.draw()
        widget = self.graph_canvas.get_tk_widget()
        widget.configure(bg="#1a1a1a", highlightthickness=0)
        widget.pack(fill="both", expand=True, padx=10, pady=10)

if __name__ == "__main__":
    init_db()
    app = TradeTrackerApp()
    
    try:
        import pyi_splash
        pyi_splash.close()
    except ImportError:
        pass
        
    app.mainloop()
