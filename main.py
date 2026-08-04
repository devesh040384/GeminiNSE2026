import logging
import sys
import time
import os
import json
import pyotp
import sqlite3
import threading
from datetime import datetime

# Import the new Reconciler we just created
from startup_sync import TradeReconciler 

from dotenv import load_dotenv, find_dotenv

from order_execution import OrderExecutionEngine
from options_chain_builder import DynamicOptionsChainBuilder
from strategy_brain import StrategyBrain


# Load Environment Variables for Angel One Credentials
dotenv_path = find_dotenv(filename='.env', raise_error_if_not_found=False)
if dotenv_path:
    load_dotenv(dotenv_path=dotenv_path, override=True)
else:
    load_dotenv(override=True)

try:
    from SmartApi.smartConnect import SmartConnect
    from SmartApi.smartWebSocketV2 import SmartWebSocketV2
except ModuleNotFoundError:
    from smartapi.smartConnect import SmartConnect
    from smartapi.smartWebSocketV2 import SmartWebSocketV2

# =======================================================================
# 🛠️ DatabaseManager
# =======================================================================
try:
    from database import migrate_database_schema
except ImportError:
    migrate_database_schema = None

class DatabaseManager:
    """A lightweight bridge to keep OrderExecutionEngine happy."""
    def __init__(self, db_path='trade_history.db'):
        self.db_path = db_path
        if migrate_database_schema:
            try:
                migrate_database_schema(self.db_path)
            except TypeError:
                migrate_database_schema()
        logging.info("✅ Local DatabaseManager initialized.")
        
    def get_connection(self):
        # timeout=20 prevents "database is locked" crashes
        return sqlite3.connect(self.db_path, check_same_thread=False, timeout=20.0)
# =======================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

class AIFNOBot:
    def __init__(self):
        logging.info("Initializing F&O Framework (🛑 RESTRICTED TO NIFTY ONLY 🛑)")
        
        self.db = DatabaseManager()
        
        # 1. Load JSON Scrip Master Cache
        self.scrip_master_data = []
        try:
            if os.path.exists('scrip_master.json'):
                with open('scrip_master.json', 'r') as f:
                    self.scrip_master_data = json.load(f)
                logging.info(f"📁 Successfully loaded scrip master from local cache ({len(self.scrip_master_data)} tokens).")
        except Exception as e:
            logging.warning(f"⚠️ Could not load local scrip master cache: {e}")

        self.smart_api = None
        self.feed_token = None
        self.sws = None  
        self.tick_counter = 0  
        self.last_heartbeat = {}  
        
        # 2. Authenticate via .env credentials
        self._init_broker_session()

        # 3. Options Chain Builders (Feed Loaded JSON Data)
        self.options_builders = {}
        for token, index_name in [('26000', 'NIFTY')]:
            builder = DynamicOptionsChainBuilder(index_name=index_name, smart_api=self.smart_api)
            
            # Pass loaded scrip data into the builder attributes
            builder.scrip_master_data = self.scrip_master_data
            builder.scrip_data = self.scrip_master_data
            builder.scrip_master = self.scrip_master_data
            
            try:
                builder.load_scrip_master(self.scrip_master_data)
            except TypeError:
                builder.load_scrip_master()
                
            self.options_builders[token] = builder

        # 4. Order Execution Engine
        self.order_engine = OrderExecutionEngine(
            smart_api=self.smart_api, 
            db_manager=self.db, 
            scrip_master=self.scrip_master_data, 
            paper_trading=True
        )
        
        # 🛑 DAILY LIMIT & SHADOW LOGGING PATCH
        self._apply_shadow_logging_patch()
        
        # 5. Strategy Brain (Feed Loaded JSON Data & Builders)
        try:
            self.strategy = StrategyBrain(
                order_engine=self.order_engine, 
                options_builders=self.options_builders,
                scrip_master_data=self.scrip_master_data
            )
        except TypeError:
            self.strategy = StrategyBrain(
                order_engine=self.order_engine, 
                options_builders=self.options_builders
            )
            # Ensure attributes are populated on strategy instance
            setattr(self.strategy, 'scrip_master_data', self.scrip_master_data)
            setattr(self.strategy, 'scrip_data', self.scrip_master_data)
            setattr(self.strategy, 'scrip_master', self.scrip_master_data)
        
        # 🚀 Start Background Threads for Monitoring Exits and EOD
        threading.Thread(target=self._continuous_exit_monitor, daemon=True).start()
        threading.Thread(target=self._continuous_eod_monitor, daemon=True).start()
        
        logging.info("✅ Framework fully loaded and ready for NIFTY live feeds.")

    def _apply_shadow_logging_patch(self):
        """Intercepts order execution if the daily limit of 10 trades is reached."""
        execution_method_name = 'execute_options_order'
        original_execute = getattr(self.order_engine, execution_method_name, None)

        if original_execute:
            def shadow_wrapper(*args, **kwargs):
                count = self._get_daily_trade_count()
                if count >= 10:
                    logging.info(f"👻 [SHADOW SIGNAL] Daily limit (10) reached. Valid NIFTY setup generated but skipped execution.")
                    return {"status": "SHADOW_LOGGED"}
                return original_execute(*args, **kwargs)
                
            setattr(self.order_engine, execution_method_name, shadow_wrapper)
            logging.info("🛡️ Shadow Logging / Daily Limit interceptor active.")

    def _get_daily_trade_count(self):
        """Counts how many trades have been executed today."""
        try:
            today_str = datetime.now().strftime("%Y-%m-%d")
            conn = sqlite3.connect('trade_history.db', timeout=20.0)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM trades WHERE entry_timestamp LIKE ?", (today_str + '%',))
            count = cursor.fetchone()[0]
            conn.close()
            return count
        except Exception:
            return 0

    def _init_broker_session(self):
        try:
            api_key = os.getenv('SMARTAPI_KEY') or os.getenv('SMART_API_KEY') or os.getenv('API_KEY') or os.getenv('ANGEL_API_KEY')
            client_id = os.getenv('CLIENT_ID') or os.getenv('SMART_CLIENT_ID') or os.getenv('USER_ID')
            password = os.getenv('PIN') or os.getenv('SMART_PASSWORD') or os.getenv('PASSWORD')
            totp_secret = os.getenv('TOTP_SECRET') or os.getenv('TOTP')
            
            if not api_key or not client_id or not password or not totp_secret:
                logging.error(f"❌ CREDENTIAL ERROR: Missing credentials in .env file.")
                sys.exit(1)

            totp_code = pyotp.TOTP(totp_secret.replace(" ", "")).now()
            obj = SmartConnect(api_key=api_key)
            data = obj.generateSession(client_id, password, totp_code)
            
            if data and data.get('status'):
                self.smart_api = obj
                self.feed_token = obj.getfeedToken()
                logging.info("🔐 Successfully authenticated with SmartAPI using TOTP.")
            else:
                logging.error(f"❌ Broker authentication failed: {data}")
                sys.exit(1)
        except Exception as e:
            logging.error(f"❌ Exception during broker session initialization: {e}")
            sys.exit(1)

    def _continuous_exit_monitor(self):
        """🎯 RATE-LIMITED EXIT MONITOR: Runs in background, checks open trades."""
        logging.info("🛡️ Rate-Limited Exit Monitor active.")
        while True:
            try:
                conn = sqlite3.connect('trade_history.db', timeout=20.0)
                cursor = conn.cursor()
                cursor.execute("SELECT id, symbol, token, type, target_spot, stop_spot FROM trades WHERE status='OPEN'")
                open_trades = cursor.fetchall()
                conn.close()
                
                if not open_trades:
                    time.sleep(10)
                    continue

                for trade in open_trades:
                    trade_id, symbol, token, t_type, target_premium, stop_premium = trade
                    
                    try:
                        exchange = "BFO" if "SENSEX" in symbol else "NFO"
                        response = self.smart_api.ltpData(exchange, symbol, token)
                        
                        if response and response.get('status'):
                            live_ltp = response['data']['ltp']
                            exit_triggered = False
                            exit_reason = ""

                            if target_premium and live_ltp >= target_premium:
                                exit_triggered, exit_reason = True, "TARGET HIT"
                            elif stop_premium and live_ltp <= stop_premium:
                                exit_triggered, exit_reason = True, "STOPLOSS HIT"

                            if exit_triggered:
                                conn = sqlite3.connect('trade_history.db', timeout=20.0)
                                cursor = conn.cursor()
                                cursor.execute(
                                    "UPDATE trades SET status=?, exit_price=?, exit_time=CURRENT_TIMESTAMP, exit_reason=? WHERE id=?", 
                                    (f"CLOSED - {exit_reason}", live_ltp, exit_reason, trade_id)
                                )
                                conn.commit()
                                conn.close()
                                logging.info(f"🚨 [EXIT EXECUTED] {symbol} | Reason: {exit_reason} | Exit Premium: ₹{live_ltp:.2f}")

                    except Exception as e:
                        logging.error(f"❌ Exception fetching live LTP for {symbol}: {e}")

                    time.sleep(1.0)

            except Exception as e:
                logging.error(f"❌ Error in auto-exit monitor: {e}")

            time.sleep(10)

    def _continuous_eod_monitor(self):
        """🎯 EOD GUARD: Force-closes all open positions at 15:20 (3:20 PM) daily."""
        while True:
            now = datetime.now()
            if now.hour == 15 and now.minute >= 20:
                try:
                    conn = sqlite3.connect('trade_history.db', timeout=20.0)
                    cursor = conn.cursor()
                    cursor.execute("SELECT id, symbol FROM trades WHERE status='OPEN'")
                    open_trades = cursor.fetchall()
                    
                    if open_trades:
                        for trade in open_trades:
                            trade_id, symbol = trade
                            logging.info(f"🚨 [EOD SQUARE-OFF] Force closing intraday position: {symbol}")
                            cursor.execute("UPDATE trades SET status=? WHERE id=?", ("CLOSED - EOD SQUARE OFF", trade_id))
                            conn.commit()
                            time.sleep(0.5)
                    conn.close()
                except Exception as e:
                    logging.error(f"❌ Error during EOD square-off execution: {e}")
            
            time.sleep(30)

    def _on_data_feed(self, ws, message):
        """Live WebSocket Stream Processing"""
        try:
            self.tick_counter += 1
            token = str(message.get('token', ''))
            ltp_raw = message.get('last_traded_price')
            
            if not ltp_raw:
                return
                
            ltp = float(ltp_raw) / 100.0
            
            # 🛑 STRICT NIFTY LOCK: Mapping
            symbol_map = {'26000': 'NIFTY'}
            symbol = symbol_map.get(token)
            
            if symbol and ltp > 0:
                current_time = time.time()
                last_time = self.last_heartbeat.get(symbol, 0)
                
                if current_time - last_time >= 20:
                    trades_today = self._get_daily_trade_count()
                    logging.info(f"💓 [HEARTBEAT] NIFTY @ {ltp:.2f} | Trades Today: {trades_today}/10")
                    self.last_heartbeat[symbol] = current_time

                # Pass clean spot price to strategy
                self.strategy.evaluate_tick(symbol=symbol, spot_price=ltp)
        except Exception as e:
            logging.error(f"❌ Error processing live data feed tick: {e}")

    def _on_open(self, ws):
        logging.info("🔌 Live WebSocket Connection Established. Subscribing to NIFTY token...")
        token_list = [
            {"exchangeType": 1, "tokens": ["26000"]}
        ]
        if self.sws: 
            self.sws.subscribe("aifno_live_feed", 1, token_list)

    def _on_close(self, ws, close_status_code, close_msg):
        logging.critical("🚨 [FATAL] Live WebSocket Connection closed.")

    def _on_error(self, ws, error, *args, **kwargs):
        """Catches and handles WebSocket errors gracefully (like EOD disconnects) without crashing."""
        logging.warning(f"⚠️ [WEBSOCKET WARNING] Connection dropped or interrupted: {error}")

    def run(self):
        logging.info("Starting broker reconciliation...")
        
        # ---------------------------------------------------------
        # NEW CODE: Broker Synchronization
        # ---------------------------------------------------------
        reconciler = TradeReconciler(smart_api=self.smart_api, db_path="trade_history.db")
        sync_success = reconciler.sync_open_positions()
        
        if not sync_success:
            logging.critical("🛑 Halting startup: Broker sync failed. Check API connection.")
            return # Prevents the bot from starting blindly
            
        logging.info("Launching core live WebSocket market data stream...")
        try:
            if self.smart_api and self.feed_token:
                client_id = os.getenv('CLIENT_ID') or os.getenv('SMART_CLIENT_ID', '')
                api_key = os.getenv('SMARTAPI_KEY') or os.getenv('SMART_API_KEY', '')
                
                self.sws = SmartWebSocketV2(
                    auth_token=self.smart_api.access_token, 
                    api_key=api_key, 
                    client_code=client_id, 
                    feed_token=self.feed_token
                )
                self.sws.on_open = self._on_open
                self.sws.on_data = self._on_data_feed
                self.sws.on_error = self._on_error
                self.sws.on_close = self._on_close
                self.sws.connect()
            else:
                logging.error("❌ Cannot launch WebSocket: Broker session is not authenticated.")
                while True: 
                    time.sleep(1)
        except KeyboardInterrupt:
            logging.info("🛑 Bot stopped gracefully by user.")

if __name__ == "__main__":
    bot = AIFNOBot()
    bot.run()
