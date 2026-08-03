import sqlite3
import pandas as pd
from datetime import datetime
import os

print("Script started! Loading database...")

DB_PATH = "trade_history.db"

def run_dashboard():
    if not os.path.exists(DB_PATH):
        print(f"Database file '{DB_PATH}' not found.")
        return
        
    try:
        conn = sqlite3.connect(DB_PATH)
        df = pd.read_sql_query("SELECT * FROM trade_history WHERE status='CLOSED'", conn)
        conn.close()
        print(f"Successfully loaded {len(df)} closed trades from database.")
    except Exception as e:
        print(f"Error reading database: {e}")
        return

    if df.empty:
        print("No CLOSED trades found in the database yet.")
        return

    # Auto-detect the time column
    time_cols = ['entry_timestamp', 'exit_timestamp']
    time_col = None
    for col in time_cols:
        if col in df.columns:
            time_col = col
            break
            
    if not time_col:
        print(f"Could not find a valid time column. Available columns: {list(df.columns)}")
        return

    # Process Data
    df['report_time'] = pd.to_datetime(df[time_col], errors='coerce') 
    df = df.dropna(subset=['report_time']) 
    
    if 'pnl_rupees' not in df.columns:
        df['pnl_rupees'] = 0.0
        
    df['is_win'] = df['pnl_rupees'] > 0
    df.set_index('report_time', inplace=True)

    # Calculate Timeframes
    now = pd.Timestamp.now().normalize()
    df_daily = df[df.index >= now]
    start_of_week = now - pd.Timedelta(days=now.dayofweek)
    df_weekly = df[df.index >= start_of_week]
    start_of_month = now.replace(day=1)
    df_monthly = df[df.index >= start_of_month]

    print("\n" + "="*45)
    print("        ALGO TRADING PERFORMANCE DESK")
    print("="*45 + "\n")
    
    def generate_metrics(df_slice, title):
        print(f"=============================================")
        print(f" 📊 {title} ")
        print(f"=============================================")
        if df_slice.empty:
            print("   No closed trades in this period.\n")
            return
            
        wins = df_slice['is_win'].sum()
        total_trades = len(df_slice)
        losses = total_trades - wins
        win_rate = (wins / total_trades) * 100 if total_trades > 0 else 0
        
        total_pnl = df_slice['pnl_rupees'].sum()
        max_profit = df_slice['pnl_rupees'].max()
        max_loss = df_slice['pnl_rupees'].min()
        
        status_icon = "🟢" if total_pnl >= 0 else "🔴"
        
        print(f"   Total Trades : {total_trades}")
        print(f"   Win Rate     : {win_rate:.1f}% ({wins}W / {losses}L)")
        print(f"   Net P&L      : {status_icon} ₹{total_pnl:,.2f}")
        
        if max_profit != 0 or max_loss != 0:
            print(f"   Best Trade   : 🏆 ₹{max_profit:,.2f}")
            print(f"   Worst Trade  : 💔 ₹{max_loss:,.2f}")
        print(f"=============================================\n")

    generate_metrics(df_daily, "DAILY REPORT (Today)")
    generate_metrics(df_weekly, "WEEKLY REPORT (This Week)")
    generate_metrics(df_monthly, "MONTHLY REPORT (This Month)")
    generate_metrics(df, "ALL-TIME REPORT (Total DB History)")

if __name__ == "__main__":
    run_dashboard()
