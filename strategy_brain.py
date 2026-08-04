import logging
import time
import collections
import pandas as pd
from datetime import datetime
import json
import os

class StrategyBrain:
    def __init__(self, order_engine, options_builders, scrip_master_data=None):
        self.order_engine = order_engine
        self.options_builders = options_builders
        self.scrip_master_data = scrip_master_data
        
        # Price history buffer for calculating 14-period RSI
        self.price_history = collections.deque(maxlen=20)
        self.last_rsi = 50.0
        self.last_candle_time = time.time()
        self._last_debug_log = 0
        
        # 💾 STATE SAVER PATH
        self.state_file = "rsi_state.json"
        self._load_state() # Load memory on startup!

    def _load_state(self):
        """Loads the saved RSI buffer from a JSON file if it exists."""
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r') as f:
                    data = json.load(f)
                    # Restore prices and previous RSI
                    self.price_history.extend(data.get('price_history', []))
                    self.last_rsi = data.get('last_rsi', 50.0)
                logging.info(f"💾 [STATE RECOVERED] Restored {len(self.price_history)} minute candles and Last RSI: {self.last_rsi:.2f}")
            except Exception as e:
                logging.error(f"❌ Failed to load RSI state: {e}")

    def _save_state(self):
        """Saves the current RSI buffer to a JSON file."""
        try:
            data = {
                'price_history': list(self.price_history),
                'last_rsi': self.last_rsi
            }
            with open(self.state_file, 'w') as f:
                json.dump(data, f)
        except Exception as e:
            logging.error(f"❌ Failed to save RSI state: {e}")

    def _calculate_rsi(self, prices, period=14):
        """Calculates RSI using a rolling pandas window."""
        if len(prices) < period + 1:
            return 50.0
        s = pd.Series(list(prices))
        delta = s.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi.iloc[-1] if not pd.isna(rsi.iloc[-1]) else 50.0

    def evaluate_tick(self, symbol, spot_price, option_volume=None):
        """Evaluates live websocket ticks against the RSI strategy."""
        if symbol != "NIFTY":
            return

        current_time = time.time()
        
        # Debug logging (throttled to avoid console spam)
        if current_time - self._last_debug_log > 10:
            logging.info(f"🔎 [DEBUG - StrategyBrain] {symbol} live Spot Price received: ₹{spot_price}")
            self._last_debug_log = current_time

        state_changed = False

        # Update price history (simulate 1-min candles by capturing price every 60s)
        if current_time - self.last_candle_time >= 60:
            self.price_history.append(spot_price)
            self.last_candle_time = current_time
            state_changed = True  # A new minute closed, save state
        elif len(self.price_history) == 0:
            self.price_history.append(spot_price)
            state_changed = True
        else:
            self.price_history[-1] = spot_price # Update current unclosed candle

        # Need at least 15 data points for a valid 14-period RSI
        if len(self.price_history) < 15:
            if state_changed:
                self._save_state()
            return

        current_rsi = self._calculate_rsi(self.price_history)
        
        # 🛑 STRATEGY TRIGGER: RSI Crossover above 70
        if self.last_rsi < 70 and current_rsi >= 70:
            logging.info(f"⚡ [SIGNAL] {symbol} RSI crossed 70! (Prev: {self.last_rsi:.2f} -> Curr: {current_rsi:.2f})")
            
            # Fire the execution trigger!
            self._trigger_entry(symbol, spot_price)
            
            # Reset buffers to prevent immediate duplicate trades
            self.last_rsi = current_rsi 
            self.price_history.clear() 
            self._save_state() # Save empty state after trade
        else:
            if self.last_rsi != current_rsi:
                self.last_rsi = current_rsi
                state_changed = True

        if state_changed:
            self._save_state()

    def _trigger_entry(self, symbol, spot_price):
        """Finds the correct contract and sends it to the Order Engine."""
        token_map = {"NIFTY": "26000"}
        token = token_map.get(symbol)
        
        if not token or token not in self.options_builders:
            logging.error(f"❌ Options builder not found for {symbol}")
            return

        builder = self.options_builders[token]
        
        # Bullish RSI strategy = Call Option (CE)
        instrument_type = "CE" 
        
        # Dynamically fetch the At-The-Money (ATM) contract
        contract = builder.get_nearest_expiry_contract(spot_price=spot_price, instrument_type=instrument_type)
        
        if not contract:
            logging.error(f"❌ Could not find valid ATM {instrument_type} contract for {symbol} at Spot: {spot_price}")
            return

        contract_symbol = contract.get('symbol')
        contract_token = contract.get('token')
        strike = contract.get('strike')
        expiry = contract.get('expiry')
        
        logging.info(f"✅ Selected Valid Contract: {contract_symbol} | Expiry: {expiry} | Strike: {strike}")
        logging.info(f"🟢 [EXECUTION TRIGGER] Handing {contract_symbol} (Strike {strike}) to Order Engine...")
        
        try:
            # 1. Fetch the LIVE premium of the option contract using SmartAPI
            live_premium = 0.0
            if getattr(self.order_engine, 'smart_api', None):
                resp = self.order_engine.smart_api.ltpData("NFO", contract_symbol, contract_token)
                if resp and resp.get('status'):
                    live_premium = float(resp['data']['ltp'])
            
            if live_premium <= 0:
                logging.warning(f"⚠️ Failed to fetch live premium for {contract_symbol}. Defaulting to ₹100.00 for paper trade.")
                live_premium = 100.0 # Safety fallback for paper trading if API fails

            # 2. Calculate dynamic Target (+10%) and Stop-Loss (-5%) based on actual premium
            target_price = round(live_premium * 1.10, 2)
            stop_loss_price = round(live_premium * 0.95, 2)

            # 3. Execute the trade with ALL required arguments
            self.order_engine.execute_options_order(
                symbol=contract_symbol,
                strike=strike,
                token=contract_token,
                entry_price=live_premium,         
                target_price=target_price,        
                stop_loss_price=stop_loss_price,  
                action="BUY",
                instrument_type=instrument_type,
                entry_spot=spot_price
            )
        except Exception as e:
            logging.error(f"❌ Error while triggering entry for {symbol}: {e}")
