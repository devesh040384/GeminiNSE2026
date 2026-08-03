import logging
import sqlite3
import re
from datetime import datetime

class OrderExecutionEngine:
    def __init__(self, smart_api, db_manager, scrip_master, paper_trading_mode=True):
        self.api = smart_api
        self.db = db_manager
        self.scrip_master = scrip_master
        self.paper_trading = paper_trading_mode

    def _get_live_ltp(self, symbol, token):
        """Fetches live option premium from Angel One."""
        try:
            if not token or token == "UNKNOWN":
                return 0.0
                
            exchange = "BFO" if "SENSEX" in symbol else "NFO"
            response = self.api.ltpData(exchange, symbol, str(token))
            
            if response and response.get('status') and response.get('data'):
                return float(response['data']['ltp'])
            return None
        except Exception as e:
            logging.error(f"❌ Exception fetching live LTP for {symbol}: {e}")
            return None

    def execute_options_order(self, *args, **kwargs):
        """Universal adapter: accepts any argument format from StrategyBrain and auto-fills missing data."""
        try:
            symbol = kwargs.get('symbol') or (args[0] if len(args) > 0 else None)
            raw_type = kwargs.get('signal_type') or kwargs.get('t_type') or kwargs.get('type') or (args[1] if len(args) > 1 else None)
            qty = kwargs.get('qty') or kwargs.get('lots') or (args[2] if len(args) > 2 else 0)
            entry_spot = kwargs.get('entry_spot') or kwargs.get('spot_price') or (args[3] if len(args) > 3 else 0.0)
            
            token = kwargs.get('token')
            strike = kwargs.get('strike')

            if not symbol:
                return False

            t_type = 'PE' if raw_type and ('PE' in str(raw_type).upper() or 'PUT' in str(raw_type).upper()) else 'CE'

            if not token or not strike:
                for scrip in self.scrip_master:
                    if scrip.get('symbol') == symbol:
                        if not token: token = scrip.get('token')
                        if not strike:
                            try:
                                raw_strike = scrip.get('strike', 0)
                                strike = float(raw_strike) / 100.0 if float(raw_strike) > 100000 else float(raw_strike)
                            except: pass
                        break
                        
            if not strike:
                match = re.search(r'(\d+)(CE|PE)$', str(symbol))
                strike = float(match.group(1)) if match else 0.0
                    
            if not token: token = "UNKNOWN"

            if self.paper_trading:
                return self._execute_paper_order(symbol, token, strike, t_type, qty, entry_spot, 0.0)
            return False
                
        except Exception as e:
            logging.error(f"❌ Critical error routing options order: {e}")
            return False

    def _execute_paper_order(self, symbol, token, strike, t_type, qty, entry_spot, fallback_premium):
        """Executes the paper trade and calculates Premium-based Targets & Stop Loss."""
        try:
            entry_premium = self._get_live_ltp(symbol, token)
            
            if not entry_premium:
                entry_premium = fallback_premium or 0.0
                logging.warning(f"⚠️ Proceeding with ₹0.00 entry premium for {symbol} to prevent crash.")

            # 🎯 FIX: Calculate Target & SL based entirely on Option Premium!
            # Default: 20% Profit Target, 10% Stop Loss
            target_premium = round(entry_premium * 1.20, 2)
            stop_premium = round(entry_premium * 0.90, 2)

            logging.info(f"📋 [PAPER ORDER EXECUTED] Symbol: {symbol} | Strike: {strike} | Qty: {qty} | Entry Premium: ₹{entry_premium} | Target Premium: ₹{target_premium} | SL Premium: ₹{stop_premium}")
            
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            conn = sqlite3.connect('trade_history.db')
            cursor = conn.cursor()
            
            # We save the premium targets into the target/spot columns so we don't have to rebuild your DB structure
            query = """
                INSERT INTO trades (symbol, token, strike, type, qty, entry_price, entry_spot, target_spot, stop_spot, status, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            
            cursor.execute(query, (
                symbol, str(token), strike, t_type, qty, 
                entry_premium, entry_spot, target_premium, stop_premium, 
                'OPEN', timestamp
            ))
            
            conn.commit()
            conn.close()
            
            return True
            
        except Exception as e:
            logging.error(f"❌ Failed to log paper order for {symbol}: {e}")
            return False
