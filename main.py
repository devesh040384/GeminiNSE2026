import os
import time
import json
import logging
import threading
from datetime import datetime, timedelta
from dotenv import load_dotenv

from SmartApi import SmartConnect
import pyotp

from config import ACTIVE_INDICES, INDICES_CONFIG, PAPER_TRADING
from database import DatabaseManager
from options_chain_builder import DynamicOptionsChainBuilder
from order_execution import OrderExecutionEngine
from strategy_brain import StrategyBrain
from risk_monitors import TrailingStopLossMonitor, TradeReconciler

# Setup unified logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("trading_bot.log"),
        logging.StreamHandler()
    ]
)

load_dotenv()

def authenticate_broker():
    """Initializes and authenticates session with Angel One SmartAPI using TOTP."""
    try:
        api_key = os.getenv("SMART_API_KEY") or os.getenv("SMARTAPI_KEY")
        client_id = os.getenv("CLIENT_ID")
        pwd = os.getenv("PASSWORD") or os.getenv("PIN")
        totp_key = os.getenv("TOTP_SECRET")

        if not all([api_key, client_id, pwd, totp_key]):
            logging.error("❌ Missing broker credentials in .env file.")
            return None

        smart_api = SmartConnect(api_key=api_key)
        totp_gen = pyotp.TOTP(totp_key).now()
        
        data = smart_api.generateSession(client_id, pwd, totp_gen)
        if data and data.get('status'):
            logging.info("🔐 Successfully authenticated with SmartAPI using TOTP.")
            return smart_api
        else:
            logging.error(f"❌ Authentication failed: {data}")
            return None
    except Exception as e:
        logging.error(f"❌ Critical error during broker authentication: {e}")
        return None

def load_scrip_master_cache():
    """Loads local scrip master cache file if available."""
    if os.path.exists('scrip_master.json'):
        try:
            with open('scrip_master.json', 'r', encoding='utf-8') as f:
                data = json.load(f)
                logging.info(f"📁 Loaded scrip master cache ({len(data)} tokens).")
                return data
        except Exception as e:
            logging.error(f"❌ Failed to load scrip_master.json: {e}")
    return []

def main():
    logging.info(f"Initializing Multi-Index Framework for: {ACTIVE_INDICES}")
    
    # 1. Initialize Database Manager
    db_manager = DatabaseManager('trade_history.db')
    
    # 2. Authenticate Broker Session
    smart_api = authenticate_broker()
    
    # 3. Load Scrip Master
    scrip_master = load_scrip_master_cache()
    
    # 4. Initialize Order Execution Engine
    order_engine = OrderExecutionEngine(
        smart_api=smart_api,
        db_manager=db_manager,
        scrip_master=scrip_master,
        paper_trading=PAPER_TRADING
    )
    
    # 5. Initialize Options Chain Builders & Strategy Brain per Active Index
    options_builders = {}
    for symbol in ACTIVE_INDICES:
        cfg = INDICES_CONFIG[symbol]
        token = cfg["index_token"]
        builder = DynamicOptionsChainBuilder(index_name=symbol, smart_api=smart_api)
        builder.load_scrip_master(scrip_master)
        options_builders[token] = builder

    strategy_brain = StrategyBrain(
        order_engine=order_engine,
        options_builders=options_builders,
        scrip_master_data=scrip_master
    )
    
    # 6. Start Risk & Trailing Stop-Loss Monitors
    tsl_monitor = TrailingStopLossMonitor(db_manager=db_manager, smart_api=smart_api)
    tsl_monitor.start()
    logging.info("🛡️ Trailing Stop-Loss Exit Monitor active.")

    # 7. Broker Position Reconciliation
    if smart_api:
        logging.info("Starting broker reconciliation...")
        try:
            reconciler = TradeReconciler(smart_api=smart_api, db_manager=db_manager)
            reconciler.reconcile()
            logging.info("✅ Broker reconciliation complete.")
        except Exception as e:
            logging.error(f"❌ Error during trade reconciliation block: {e}")

    logging.info("✅ Multi-Index Framework fully operational.")

    # 8. Start WebSocket Live Feed Integration
    if smart_api:
        from SmartApi.smartWebSocketV2 import SmartWebSocketV2
        
        client_code = os.getenv("CLIENT_ID")
        feed_token = os.getenv("FEED_TOKEN")
        api_key = os.getenv("SMART_API_KEY") or os.getenv("SMARTAPI_KEY")
        
        # Dynamically fetch feed token if missing or empty in .env
        if not feed_token or feed_token == "your_feed_token_here":
            try:
                feed_resp = smart_api.getfeedToken()
                if isinstance(feed_resp, dict):
                    feed_token = feed_resp.get('data') or feed_resp.get('feedToken')
                else:
                    feed_token = feed_resp
                logging.info("🔑 Feed token generated dynamically from active session.")
            except Exception as e:
                logging.error(f"❌ Failed to fetch feed token: {e}")
        
        if not feed_token and hasattr(smart_api, 'feedToken'):
            feed_token = smart_api.feedToken

        if client_code and feed_token:
            # Initialize WebSocket with explicit keyword arguments matching SmartWebSocketV2 signature
            sws = SmartWebSocketV2(
                auth_token=smart_api.access_token,
                api_key=api_key,
                client_code=client_code,
                feed_token=feed_token
            )
            
            def on_data(ws, message):
                try:
                    token = str(message.get('token') or message.get('exchangeToken'))
                    ltp_raw = message.get('last_traded_price') or message.get('ltp')
                    
                    if ltp_raw:
                        spot_price = float(ltp_raw) / 100.0 if float(ltp_raw) > 1000000 else float(ltp_raw)
                        
                        for sym, cfg in INDICES_CONFIG.items():
                            if str(cfg["index_token"]) == token:
                                strategy_brain.evaluate_tick(sym, spot_price)
                except Exception as ex:
                    logging.error(f"❌ Error processing websocket tick: {ex}")

            def on_open(ws):
                logging.info("🔌 Live WebSocket Connection Established. Subscribing tokens...")
                token_list = []
                for sym in ACTIVE_INDICES:
                    cfg = INDICES_CONFIG[sym]
                    exch_type = cfg.get("exchange_type", 1)
                    token_list.append({"exchangeType": exch_type, "tokens": [str(cfg["index_token"])]})
                
                sws.subscribe("corrid_multindex", 1, token_list)
                logging.info(f"📡 Subscribed to indices: {ACTIVE_INDICES}")

            def on_error(ws, error):
                logging.error(f"❌ WebSocket Error: {error}")

            def on_close(ws):
                logging.warning("⚠️ WebSocket Connection Closed.")

            sws.on_open = on_open
            sws.on_data = on_data
            sws.on_error = on_error
            sws.on_close = on_close

            logging.info("Launching core live WebSocket market data stream...")
            sws.connect()
        else:
            logging.error("❌ FEED_TOKEN could not be obtained. Cannot start WebSocket stream.")
    else:
        logging.warning("⚠️ Running without active broker SmartAPI connection.")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logging.info("🛑 Bot stopped manually by user.")
    except Exception as e:
        logging.critical(f"❌ Fatal crash in main loop: {e}", exc_info=True)
