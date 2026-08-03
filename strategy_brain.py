import logging
import sqlite3
import time
from collections import deque
import statistics

class StrategyBrain:
    def __init__(self, order_engine, options_builders):
        self.order_engine = order_engine
        self.options_builders = options_builders
        
        # State tracking for NIFTY only
        self.market_state = {
            "NIFTY": {
                "prices": deque(maxlen=14),  
                "last_rsi": None
            }
        }
        
        self.log_counter = 0
        self.last_signal_time = 0  # Cooldown timer

    def _has_open_position(self):
        """Checks the database to ensure we don't open multiple overlapping trades."""
        try:
            # timeout=10 prevents crashes if another thread is reading the DB
            conn = sqlite3.connect('trade_history.db', timeout=10.0)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM trades WHERE status='OPEN'")
            count = cursor.fetchone()[0]
            conn.close()
            return count > 0
        except Exception as e:
            logging.error(f"❌ DB Check Error in StrategyBrain: {e}")
            # Failsafe: If the DB is locked/failing, assume a trade is open to prevent spam
            return True 

    def evaluate_tick(self, symbol, spot_price):
        """Processes live incoming WebSocket ticks."""
        if symbol != "NIFTY":
            return
            
        state = self.market_state["NIFTY"]
        state["prices"].append(spot_price)

        self.log_counter += 1
        if self.log_counter % 50 == 0:
            logging.info(f"🔎 [DEBUG - StrategyBrain] {symbol} live Spot Price received: ₹{spot_price:.2f}")

        if len(state["prices"]) < 14:
            return

        current_rsi = self._calculate_rsi(list(state["prices"]))
        current_time = time.time()
        
        if state["last_rsi"] is not None:
            # RSI crosses 70 from below
            if state["last_rsi"] <= 70 and current_rsi > 70:
                
                # 🛑 SAFETY CHECK 1: Cooldown Timer (Prevent Millisecond Spam)
                if current_time - self.last_signal_time < 60:
                    pass # Ignore signal silently during cooldown
                    
                # 🛑 SAFETY CHECK 2: Database Position Check (Prevent Overlapping Trades)
                elif self._has_open_position():
                    if self.log_counter % 50 == 0:  # Only log periodically to avoid terminal spam
                        logging.info(f"⏳ [SKIP] {symbol} RSI > 70, but we already have an OPEN trade.")
                        
                else:
                    # ✅ All checks passed. Fire the trade!
                    logging.info(f"⚡ [SIGNAL] {symbol} RSI crossed 70! (Prev: {state['last_rsi']:.2f} -> Curr: {current_rsi:.2f})")
                    self.last_signal_time = current_time
                    self._trigger_entry(symbol, spot_price)

        state["last_rsi"] = current_rsi

    def _calculate_rsi(self, prices, period=14):
        """Pure Python RSI calculation to eliminate dependency issues."""
        if len(prices) < period:
            return 50.0

        gains = []
        losses = []

        for i in range(1, len(prices)):
            difference = prices[i] - prices[i - 1]
            if difference > 0:
                gains.append(difference)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(difference))

        avg_gain = statistics.mean(gains[-period:])
        avg_loss = statistics.mean(losses[-period:])

        if avg_loss == 0:
            return 100.0

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def _trigger_entry(self, symbol, spot_price):
        """Finds the correct contract and hands it to the order engine."""
        try:
            token = "26000" if symbol == "NIFTY" else None
            if not token or token not in self.options_builders:
                logging.error(f"❌ Cannot trigger entry: Missing token or builder for {symbol}")
                return

            builder = self.options_builders[token]
            
            atm_strike = round(spot_price / 50.0) * 50
            
            scrip_data = getattr(builder, 'scrip_master_data', [])
            if not scrip_data:
                scrip_data = getattr(self.order_engine, 'scrip_master', [])

            if not scrip_data:
                logging.error("❌ Cannot trigger entry: JSON scrip master data is missing.")
                return
            
            atm_contract = builder.get_nearest_expiry_contract(
                scrip_master_data=scrip_data,
                symbol=symbol,
                option_type="CE",
                target_strike=atm_strike
            )
            
            if not atm_contract:
                logging.warning(f"⚠️ Could not resolve ATM contract for {symbol} at strike {atm_strike}.")
                return

            # Set dynamic targets based on spot price movement
            target_spot = spot_price + 20.0
            stop_spot = spot_price - 10.0

            logging.info(f"🟢 [EXECUTION TRIGGER] Handing {atm_contract.get('symbol', 'CE')} (Strike {atm_strike}) to Order Engine...")
            
            self.order_engine.execute_options_order(
                symbol=atm_contract.get('symbol'),
                token=atm_contract.get('token'),
                action="BUY",
                quantity=65, 
                target_spot=target_spot,
                stop_spot=stop_spot,
                instrument_type="CE",
                strike=atm_strike,
                entry_spot=spot_price
            )
            
        except Exception as e:
            logging.error(f"❌ Error while triggering entry for {symbol}: {e}")
