import sqlite3
from datetime import datetime, timedelta

def generate_summary():
    db_path = 'trade_history.db'
    today_str = datetime.now().strftime('%Y-%m-%d')
    
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, entry_timestamp, exit_time, symbol, action, quantity, 
                   entry_price, exit_price, status, exit_reason 
            FROM trades 
            WHERE entry_timestamp LIKE ?
            ORDER BY id ASC
        """, (f"{today_str}%",))
        
        trades = cursor.fetchall()
        conn.close()

        print(f"\n📊 ALGO TRADING DAILY SUMMARY (IST): {today_str}")
        print("=" * 125)
        
        if not trades:
            print("No trades executed today.")
            print("=" * 125 + "\n")
            return

        print(f"{'ID':<3} | {'ENTRY TIME (IST)':<19} | {'EXIT TIME (IST)':<19} | {'SYMBOL':<22} | {'ENTRY ₹':<8} | {'EXIT ₹':<8} | {'PNL %':<8} | {'NET ₹'}")
        print("-" * 125)

        total_net = 0.0
        closed_trades = 0

        for t in trades:
            tid = t['id']
            ent_time = t['entry_timestamp'] # Already stored in clean format
            ext_time = t['exit_time'] if t['exit_time'] else "OPEN"

            sym = t['symbol']
            ent_p = t['entry_price']
            ext_p = t['exit_price'] if t['exit_price'] else 0.0
            qty = t['quantity'] if t['quantity'] else 65
            
            if "CLOSED" in str(t['status']) and ext_p > 0:
                pnl_pct = ((ext_p - ent_p) / ent_p) * 100
                net_rs = (ext_p - ent_p) * qty
                total_net += net_rs
                closed_trades += 1
                pnl_str = f"{pnl_pct:+.2f}%"
                net_str = f"{net_rs:+.2f}"
            else:
                pnl_str = "-"
                net_str = "-"

            print(f"{tid:<3} | {ent_time:<19} | {ext_time:<19} | {sym:<22} | {ent_p:.2f}    | {ext_p:.2f}    | {pnl_str:<8} | {net_str}")

        print("=" * 125)
        print(f"📝 Total Closed Trades : {closed_trades}")
        print(f"💰 NET REALIZED PNL   : ₹ {total_net:+.2f}")
        print("=" * 125 + "\n")

    except Exception as e:
        print(f"❌ Error generating summary: {e}")

if __name__ == "__main__":
    generate_summary()
