import sqlite3
from datetime import datetime
import re
import sys

def parse_time(time_str):
    """Safely parse SQLite timestamp strings."""
    if not time_str:
        return None
    try:
        return datetime.strptime(time_str.split('.')[0], '%Y-%m-%d %H:%M:%S')
    except ValueError:
        return None

def format_duration(start_time, end_time):
    """Calculates hours and minutes held."""
    if not start_time or not end_time:
        return "N/A"
    duration = end_time - start_time
    total_seconds = int(duration.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m {seconds}s"

def extract_expiry(symbol):
    """Extracts expiry like '04AUG26' from 'NIFTY04AUG2624350CE'."""
    if not symbol:
        return "UNKNOWN"
    match = re.search(r'([0-9]{2}[A-Z]{3}[0-9]{2})', symbol)
    return match.group(1) if match else "UNKNOWN"

def generate_report(db_path='trade_history.db', fetch_all=False):
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        if fetch_all:
            cursor.execute("SELECT * FROM trades ORDER BY id DESC")
            report_title = "ALL TIME"
        else:
            # Get today's date in YYYY-MM-DD format to filter the SQL query
            today_str = datetime.now().strftime('%Y-%m-%d')
            cursor.execute("SELECT * FROM trades WHERE entry_timestamp LIKE ? ORDER BY id DESC", (today_str + '%',))
            report_title = today_str

        trades = cursor.fetchall()
        conn.close()
    except Exception as e:
        print(f"❌ Error reading database: {e}")
        sys.exit(1)

    completed_trades = []
    open_trades = []

    for trade in trades:
        qty = 65 
        
        raw_entry = trade['entry_timestamp']
        raw_exit = trade.get('exit_time', None)
        safe_symbol = trade['symbol'] if trade['symbol'] else "UNKNOWN"
        
        entry_time_parsed = parse_time(raw_entry)
        
        if trade['status'] and trade['status'].startswith('CLOSED'):
            exit_time_parsed = parse_time(raw_exit)
            held = format_duration(entry_time_parsed, exit_time_parsed)
            
            entry = float(trade['entry_price']) if trade['entry_price'] else 0.0
            exit_p = float(trade['exit_price']) if trade['exit_price'] else 0.0
            
            pnl_rs = (exit_p - entry) * qty
            pnl_perc = ((exit_p - entry) / entry) * 100 if entry > 0 else 0.0
            
            reason = trade['exit_reason'] if trade['exit_reason'] else trade['status']
            reason_short = reason.replace('CLOSED - ', '').replace(' HIT', '').strip()[:10]

            completed_trades.append({
                'symbol': safe_symbol[:20],
                'type': trade['type'] or 'CE',
                'entry_time': raw_entry[-8:] if raw_entry else "N/A",
                'exit_time': raw_exit[-8:] if raw_exit else "N/A",
                'held': held,
                'entry': f"{entry:.2f}",
                'exit': f"{exit_p:.2f}",
                'pnl_perc': f"{pnl_perc:+.2f}%",
                'pnl_rs': f"{pnl_rs:+.2f}",
                'result': reason_short
            })
        elif trade['status'] == 'OPEN':
            held = format_duration(entry_time_parsed, datetime.now())
            entry = float(trade['entry_price']) if trade['entry_price'] else 0.0
            tgt = float(trade['target_spot']) if trade['target_spot'] else 0.0
            sl = float(trade['stop_spot']) if trade['stop_spot'] else 0.0
            
            expiry = extract_expiry(safe_symbol)

            open_trades.append({
                'symbol': safe_symbol[:20],
                'type': trade['type'] or 'CE',
                'entry_time': raw_entry[-8:] if raw_entry else "N/A",
                'held': held,
                'entry': f"{entry:.2f}",
                'ltp': "LIVE*", 
                'tgt': f"{tgt:.2f}",
                'sl': f"{sl:.2f}",
                'pnl_perc': "---",
                'pnl_rs': "---",
                'qty': qty,
                'expiry': expiry
            })

    # --- PRINTING SECTION ---
    print("=" * 125)
    print(f"FNO COMPLETED TRADES - Report for: {report_title}")
    print("=" * 125)
    print(f"{'Symbol':<25} {'Type':<5} {'Entry Time':<12} {'Exit Time':<12} {'Held':<10} {'Entry':<8} {'Exit':<8} {'PnL%':<8} {'PnL Rs':<10} {'Result'}")
    print("-" * 125)
    
    if not completed_trades:
        print("No completed trades found for this period.")
    else:
        for t in completed_trades:
            print(f"{t['symbol']:<25} {t['type']:<5} {t['entry_time']:<12} {t['exit_time']:<12} {t['held']:<10} {t['entry']:<8} {t['exit']:<8} {t['pnl_perc']:<8} {t['pnl_rs']:<10} {t['result']}")

    print("\n\n")
    print("HOLDING TRADES")
    print(f"{'Symbol':<25} {'Type':<5} {'Entry Time':<12} {'Held':<10} {'Entry':<8} {'LTP':<8} {'Tgt':<10} {'SL':<10} {'PnL%':<8} {'PnL Rs':<8} {'Qty':<5} {'Expiry'}")
    print("-" * 125)
    
    if not open_trades:
        print("No open trades currently holding.")
    else:
        for t in open_trades:
            print(f"{t['symbol']:<25} {t['type']:<5} {t['entry_time']:<12} {t['held']:<10} {t['entry']:<8} {t['ltp']:<8} {t['tgt']:<10} {t['sl']:<10} {t['pnl_perc']:<8} {t['pnl_rs']:<8} {t['qty']:<5} {t['expiry']}")
            
    print("\n*Note: LTP and open PnL require live WebSocket/API connection. Run this inside bot for live metrics.")

if __name__ == "__main__":
    # Check if the user passed "--all" in the terminal command
    show_all = "--all" in sys.argv
    generate_report(fetch_all=show_all)
