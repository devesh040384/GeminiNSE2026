import sqlite3
import logging
from datetime import datetime, timedelta

def migrate_database_schema(db_path='trade_history.db'):
    """Ensures the SQLite database schema has all columns and tables, auto-patching if needed."""
    try:
        conn = sqlite3.connect(db_path, timeout=20.0)
        cursor = conn.cursor()
        
        # 1. Create main trades table if it doesn't exist
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_timestamp TEXT,
                exit_time TEXT,
                symbol TEXT,
                token TEXT,
                action TEXT,
                instrument_type TEXT,
                quantity INTEGER,
                entry_price REAL,
                target_price REAL,
                stop_loss_price REAL,
                exit_price REAL,
                status TEXT,
                exit_reason TEXT,
                entry_spot REAL,
                peak_price REAL,
                stop_spot REAL
            )
        """)

        # 2. Check and add missing columns dynamically to avoid mismatch errors
        cursor.execute("PRAGMA table_info(trades)")
        existing_columns = [col[1] for col in cursor.fetchall()]
        
        required_columns = {
            'target_price': 'REAL',
            'stop_loss_price': 'REAL',
            'exit_price': 'REAL',
            'exit_reason': 'TEXT',
            'entry_spot': 'REAL',
            'peak_price': 'REAL',
            'stop_spot': 'REAL',
            'instrument_type': 'TEXT'
        }
        
        for col_name, col_type in required_columns.items():
            if col_name not in existing_columns:
                cursor.execute(f"ALTER TABLE trades ADD COLUMN {col_name} {col_type}")
                logging.info(f"🛠️ [DB MIGRATION] Added missing column '{col_name}' to trades table.")

        # 3. Create study signals table for post-limit analysis
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS study_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                symbol TEXT,
                instrument_type TEXT,
                spot_price REAL,
                reason TEXT
            )
        """)

        conn.commit()
        conn.close()
        logging.info("✅ Database schema verified and migrated successfully.")
    except Exception as e:
        logging.error(f"❌ Database migration failed: {e}")

class DatabaseManager:
    """A lightweight bridge for managing database connections and logging."""
    def __init__(self, db_path='trade_history.db'):
        self.db_path = db_path
        migrate_database_schema(self.db_path)
        logging.info("✅ Local DatabaseManager initialized.")
        
    def get_connection(self):
        return sqlite3.connect(self.db_path, check_same_thread=False, timeout=20.0)

    def log_study_signal(self, symbol, spot_price, instrument_type, reason="STUDY_TRIGGER"):
        """Logs post-limit signals for study/backtesting purposes without executing orders."""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            ist_time = (datetime.utcnow() + timedelta(hours=5, minutes=30)).strftime('%Y-%m-%d %H:%M:%S')
            cursor.execute("""
                INSERT INTO study_signals (timestamp, symbol, instrument_type, spot_price, reason)
                VALUES (?, ?, ?, ?, ?)
            """, (ist_time, symbol, instrument_type, spot_price, reason))
            conn.commit()
            conn.close()
        except Exception as e:
            logging.error(f"❌ Failed to log study signal: {e}")

def log_paper_order(*args, **kwargs):
    """Flexible paper order logger supporting both dictionary and keyword argument payloads."""
    try:
        db_path = kwargs.get('db_path', 'trade_history.db')
        
        if args and isinstance(args[0], dict):
            d = args[0]
            symbol = d.get('symbol')
            token = d.get('token')
            action = d.get('action', 'BUY')
            inst_type = d.get('instrument_type', 'CE')
            qty = d.get('quantity', 65)
            entry_p = d.get('entry_price')
            target_p = d.get('target_price')
            sl_p = d.get('stop_loss_price')
            spot = d.get('entry_spot', 0.0)
        else:
            symbol = kwargs.get('symbol')
            token = kwargs.get('token')
            action = kwargs.get('action', 'BUY')
            inst_type = kwargs.get('instrument_type', 'CE')
            qty = kwargs.get('quantity', 65)
            entry_p = kwargs.get('entry_price')
            target_p = kwargs.get('target_price')
            sl_p = kwargs.get('stop_loss_price')
            spot = kwargs.get('entry_spot', 0.0)

        conn = sqlite3.connect(db_path, timeout=20.0)
        cursor = conn.cursor()
        ist_time = (datetime.utcnow() + timedelta(hours=5, minutes=30)).strftime('%Y-%m-%d %H:%M:%S')
        
        cursor.execute("""
            INSERT INTO trades (
                entry_timestamp, symbol, token, action, instrument_type, 
                quantity, entry_price, target_price, stop_loss_price, 
                status, entry_spot, peak_price, stop_spot
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, ?, ?)
        """, (
            ist_time, symbol, token, action, inst_type, 
            qty, entry_p, target_p, sl_p, 
            spot, entry_p, sl_p
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"❌ Failed to log paper order to database: {e}")
