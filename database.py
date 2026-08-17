import sqlite3
import logging
from contextlib import contextmanager
from datetime import datetime

class DatabaseManager:
    def __init__(self, db_path='trade_history.db'):
        self.db_path = db_path
        self.init_database()

    def get_connection(self):
        # timeout=15 and check_same_thread=False for safe multithreading
        conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=15.0)
        conn.row_factory = sqlite3.Row
        
        # Enable WAL mode so Heartbeat, TSL Monitor, and WebSocket never block each other
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn

    @contextmanager
    def get_cursor(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except Exception as e:
            conn.rollback()
            logging.error(f"❌ Database transaction error: {e}")
            raise
        finally:
            conn.close()

    def init_database(self):
        try:
            with self.get_cursor() as cursor:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS trades (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        symbol TEXT NOT NULL,
                        token TEXT,
                        entry_price REAL,
                        target_price REAL,
                        stop_loss_price REAL,
                        peak_price REAL,
                        status TEXT,
                        exit_price REAL,
                        exit_time TEXT,
                        exit_reason TEXT,
                        timestamp TEXT
                    )
                """)
            logging.info("✅ Local DatabaseManager initialized (WAL Mode Active, IST Timestamps).")
        except Exception as e:
            logging.critical(f"❌ Fatal error initializing database schema: {e}")

    def log_trade(self, symbol, token, entry_price, target_price, stop_loss_price, status="OPEN"):
        """Logs a new trade with an explicit local IST timestamp."""
        try:
            now_ist = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with self.get_cursor() as cursor:
                cursor.execute("""
                    INSERT INTO trades (symbol, token, entry_price, target_price, stop_loss_price, peak_price, status, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (symbol, token, entry_price, target_price, stop_loss_price, entry_price, status, now_ist))
                logging.info(f"💾 [DB] Successfully logged trade entry for {symbol} at ₹{entry_price}")
        except Exception as e:
            logging.error(f"❌ Failed to log trade for {symbol} into database: {e}")

    def update_trailing_stoploss(self, trade_id, new_sl_price, new_peak_price):
        """Used by risk_monitors.py to trail the SL upwards."""
        try:
            with self.get_cursor() as cursor:
                cursor.execute("""
                    UPDATE trades 
                    SET stop_loss_price = ?, peak_price = ? 
                    WHERE id = ?
                """, (new_sl_price, new_peak_price, trade_id))
        except Exception as e:
            logging.error(f"❌ Failed to update TSL for trade {trade_id}: {e}")

    def close_trade(self, trade_id, exit_price, exit_reason):
        """Used to mark a trade as CLOSED and logs the explicit local IST exit time."""
        try:
            now_ist = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with self.get_cursor() as cursor:
                cursor.execute("""
                    UPDATE trades 
                    SET status = 'CLOSED', exit_price = ?, exit_reason = ?, exit_time = ?
                    WHERE id = ?
                """, (exit_price, exit_reason, now_ist, trade_id))
                logging.info(f"🔒 [DB] Trade {trade_id} closed at ₹{exit_price}. Reason: {exit_reason}")
        except Exception as e:
            logging.error(f"❌ Failed to close trade {trade_id}: {e}")

    def fetch_one(self, query, params=()):
        """Used by the Heartbeat Monitor to safely count trades."""
        try:
            with self.get_cursor() as cursor:
                cursor.execute(query, params)
                return cursor.fetchone()
        except Exception as e:
            logging.error(f"❌ Database fetch_one error: {e}")
            return None

    def fetch_all(self, query, params=()):
        """Used by the TSL Monitor to safely read open trades."""
        try:
            with self.get_cursor() as cursor:
                cursor.execute(query, params)
                return cursor.fetchall()
        except Exception as e:
            logging.error(f"❌ Database fetch_all error: {e}")
            return []
