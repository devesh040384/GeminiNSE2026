import sqlite3
import pandas as pd
from datetime import datetime

def run_performance_summary():
    conn = sqlite3.connect("trade_history.db")
    
    query = """
    SELECT 
        id, 
        entry_timestamp, 
        symbol, 
        type as action, 
        entry_price, 
        status
    FROM trades 
    ORDER BY id DESC;
    """
    
    df = pd.read_sql_query(query, conn)
    conn.close()
    
    if df.empty:
        print("⚠️ No trade history found in trade_history.db.")
        return

    # Convert timestamps to datetime objects
    df['entry_timestamp'] = pd.to_datetime(df['entry_timestamp'], errors='coerce')
    
    # Extract period identifiers for grouping
    df['Date'] = df['entry_timestamp'].dt.date
    df['Week'] = df['entry_timestamp'].dt.to_period('W').astype(str)
    df['Month'] = df['entry_timestamp'].dt.to_period('M').astype(str)

    print("=" * 70)
    print("               📊 ALGO TRADING PERIODIC TRADE SUMMARY             ")
    print("=" * 70)
    print(f" 🗓️ Report Generated (IST) : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f" 📦 Total Trades Logged   : {len(df)}")
    print("=" * 70)

    # 1. DAILY BREAKDOWN
    print("\n📅 1. TRADES BY DAY:")
    print("-" * 70)
    daily_summary = df.groupby('Date').agg(Total_Trades=('id', 'count')).reset_index()
    print(daily_summary.to_string(index=False))

    # 2. WEEKLY BREAKDOWN
    print("\n📈 2. TRADES BY WEEK:")
    print("-" * 70)
    weekly_summary = df.groupby('Week').agg(Total_Trades=('id', 'count')).reset_index()
    print(weekly_summary.to_string(index=False))

    # 3. MONTHLY BREAKDOWN
    print("\n📊 3. TRADES BY MONTH:")
    print("-" * 70)
    monthly_summary = df.groupby('Month').agg(Total_Trades=('id', 'count')).reset_index()
    print(monthly_summary.to_string(index=False))

    print("\n" + "=" * 70)
    print("📋 DETAILED TRADE LOGS:")
    print("-" * 70)
    display_cols = ['id', 'entry_timestamp', 'symbol', 'action', 'entry_price', 'status']
    print(df[display_cols].to_string(index=False))
    print("=" * 70)

if __name__ == "__main__":
    run_performance_summary()
