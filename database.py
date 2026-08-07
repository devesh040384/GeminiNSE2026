import sqlite3
import logging
from contextlib import contextmanager

class DatabaseManager:
    def __init__(self, db_path='trade_history.db'):
        self.db_path = db_path
        self.init_database()

    def get_connection(self):
        """Returns a standard sqlite3 connection with row factory."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def get_cursor(self):
        """Context manager for safe cursor and connection handling."""
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
        """Initializes required SQLite tables safely without breaking startup."""
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
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                """)
            logging.info("✅ Local DatabaseManager initialized cleanly.")
        except Exception as e:
            logging.critical(f"❌ Fatal error initializing database schema: {e}")

    def log_trade(self, symbol, token, entry_price, target_price, stop_loss_price, status="OPEN"):
        """Safely logs a new trade without crashing the main execution flow if an error occurs."""
        try:
            with self.get_cursor() as cursor:
                cursor.execute("""
                    INSERT INTO trades (symbol, token, entry_price, target_price, stop_loss_price, peak_price, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (symbol, token, entry_price, target_price, stop_loss_price, entry_price, status))
                logging.info(f"💾 [DB] Successfully logged trade entry for {symbol} at ₹{entry_price}")
        except Exception as e:
            logging.error(f"❌ Failed to log trade for {symbol} into database: {e}")
