import sqlite3
import logging
from datetime import datetime

DB_PATH = 'trade_history.db'

def get_connection(db_path=DB_PATH):
    """
    Returns a database connection with a 20.0-second timeout 
    to prevent 'database is locked' errors during rapid live ticks.
    """
    conn = sqlite3.connect(db_path, timeout=20.0)
    conn.row_factory = sqlite3.Row
    return conn

def init_db(db_path=DB_PATH):
    """
    Initializes the database schema with all modern columns.
    Includes both 'qty' and 'quantity' columns to prevent schema mismatch errors.
    """
    try:
        conn = get_connection(db_path)
        cursor = conn.cursor()

        # 1. Base table creation containing all columns used across the bot
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_timestamp TEXT,
                exit_time TEXT,
                symbol TEXT,
                token TEXT,
                action TEXT,
                quantity INTEGER,
                qty INTEGER,
                entry_price REAL,
                exit_price REAL,
                target_spot REAL,
                stop_spot REAL,
                status TEXT,
                exit_reason TEXT,
                type TEXT,
                instrument_type TEXT,
                strike REAL,
                entry_spot REAL
            )
        ''')

        # 2. Auto-migration check: ensure any pre-existing DB gets missing columns added dynamically
        required_columns = [
            ("entry_timestamp", "TEXT"),
            ("exit_time", "TEXT"),
            ("symbol", "TEXT"),
            ("token", "TEXT"),
            ("action", "TEXT"),
            ("quantity", "INTEGER"),
            ("qty", "INTEGER"),
            ("entry_price", "REAL"),
            ("exit_price", "REAL"),
            ("target_spot", "REAL"),
            ("stop_spot", "REAL"),
            ("status", "TEXT"),
            ("exit_reason", "TEXT"),
            ("type", "TEXT"),
            ("instrument_type", "TEXT"),
            ("strike", "REAL"),
            ("entry_spot", "REAL")
        ]

        cursor.execute("PRAGMA table_info(trades)")
        existing_cols = [col[1] for col in cursor.fetchall()]

        for col_name, col_type in required_columns:
            if col_name not in existing_cols:
                cursor.execute(f"ALTER TABLE trades ADD COLUMN {col_name} {col_type}")
                logging.info(f"⚙️ Auto-Migration: Added missing column '{col_name}' to trades table.")

        conn.commit()
        conn.close()
        logging.info("✅ Database schema verified and fully aligned.")
    except Exception as e:
        logging.error(f"❌ Database initialization error: {e}")

def log_paper_order(symbol, token="", action="BUY", qty=65, quantity=65, entry_price=0.0, target_spot=0.0, stop_spot=0.0, instrument_type="CE", strike=0.0, entry_spot=0.0, db_path=DB_PATH):
    """
    Logs a paper trade into the SQLite database.
    Guarantees lot size defaults to 65 if 0 is passed.
    """
    try:
        conn = get_connection(db_path)
        cursor = conn.cursor()
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # Fallback logic to prevent Qty: 0
        final_qty = qty if (qty and qty > 0) else (quantity if (quantity and quantity > 0) else 65)

        cursor.execute('''
            INSERT INTO trades (
                entry_timestamp, symbol, token, action, quantity, qty, entry_price,
                target_spot, stop_spot, status, type, instrument_type, strike, entry_spot
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, ?, ?, ?)
        ''', (
            now_str, symbol, str(token), action, final_qty, final_qty, entry_price,
            target_spot, stop_spot, instrument_type, instrument_type, strike, entry_spot
        ))

        trade_id = cursor.lastrowid
        conn.commit()
        conn.close()
        logging.info(f"💾 Trade #{trade_id} logged to DB for {symbol} | Strike: {strike} | Qty: {final_qty} | Entry: ₹{entry_price:.2f}")
        return trade_id
    except Exception as e:
        logging.error(f"❌ Failed to log paper order for {symbol}: {e}")
        return None

def close_trade(trade_id, exit_price, exit_reason, db_path=DB_PATH):
    """
    Updates an open trade with its exit price, exit time, and closure status.
    """
    try:
        conn = get_connection(db_path)
        cursor = conn.cursor()
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        cursor.execute('''
            UPDATE trades
            SET exit_price = ?, exit_time = ?, status = ?, exit_reason = ?
            WHERE id = ?
        ''', (exit_price, now_str, f"CLOSED - {exit_reason}", exit_reason, trade_id))

        conn.commit()
        conn.close()
        logging.info(f"🔒 Trade #{trade_id} closed at ₹{exit_price:.2f} ({exit_reason})")
        return True
    except Exception as e:
        logging.error(f"❌ Failed to close trade #{trade_id}: {e}")
        return False

def has_open_position(db_path=DB_PATH):
    """
    Checks if any trade currently has status='OPEN'.
    """
    try:
        conn = get_connection(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM trades WHERE status='OPEN'")
        count = cursor.fetchone()[0]
        conn.close()
        return count > 0
    except Exception as e:
        logging.error(f"❌ Error checking open positions: {e}")
        return True  # Return True as a safety measure to prevent duplicate orders on DB error

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    init_db()
