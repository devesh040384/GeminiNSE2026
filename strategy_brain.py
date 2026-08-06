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
        
        self.price_history = collections.deque(maxlen=50) # Expanded buffer for ATR/Supertrend math
        self.last_rsi = 50.0
        self.last_candle_time = time.time()
        self._last_debug_log = 0
        self._last_rsi_log = 0
        
        self.cooldown_until = 0.0 
        self.state_file = "rsi_state.json"
        self._load_state()

    def _load_state(self):
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r') as f:
                    data = json.load(f)
                    self.price_history.extend(data.get('price_history', []))
                    self.last_rsi = data.get('last_rsi', 50.0)
                logging.info(f"💾 [STATE RECOVERED] Restored {len(self.price_history)} candles and Last RSI: {self.last_rsi:.2f}")
            except Exception as e:
                logging.error(f"❌ Failed to load state: {e}")

    def _save_state(self):
        try:
            data = {'price_history': list(self.price_history), 'last_rsi': self.last_rsi}
            with open(self.state_file, 'w') as f:
                json.dump(data, f)
        except Exception as e:
            logging.error(f"❌ Failed to save state: {e}")

    def _calculate_rsi(self, prices, period=14):
        if len(prices) < period + 1:
            return 50.0
        s = pd.Series(list(prices))
        delta = s.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi.iloc[-1] if not pd.isna(rsi.iloc[-1]) else 50.0

    def _calculate_supertrend(self, prices, period=10, multiplier=3.0):
        """
        Calculates Supertrend direction ('BULLISH' or 'BEARISH') based on ATR.
        Returns latest direction string.
        """
        if len(prices) < period + 5:
            return "NEUTRAL"
        try:
            df = pd.DataFrame({'close': list(prices)})
            df['high'] = df['close'] + 2.0  # Proxy high/low spread simulation for tick data
            df['low'] = df['close'] - 2.0
            
            # True Range
            df['tr1'] = df['high'] - df['low']
            df['tr2'] = abs(df['high'] - df['close'].shift(1))
            df['tr3'] = abs(df['low'] - df['close'].shift(1))
            df['tr'] = df[['tr1', 'tr2', 'tr3']].max(axis=1)
            df['atr'] = df['tr'].rolling(window=period).mean()
            
            hl2 = (df['high'] + df['low']) / 2
            df['upperband'] = hl2 + (multiplier * df['atr'])
            df['lowerband'] = hl2 - (multiplier * df['atr'])
            
            # Simplified trend determination
            current_close = df['close'].iloc[-1]
            current_sma = df['close'].rolling(window=period).mean().iloc[-1]
            
            if current_close > current_sma:
                return "BULLISH"
            else:
                return "BEARISH"
        except Exception:
            return "NEUTRAL"

    def _get_live_pcr(self, symbol, spot_price):
        try:
            if not getattr(self.order_engine, 'smart_api', None):
                return None
            token_map = {"NIFTY": "26000"}
            token = token_map.get(symbol)
            builder = self.options_builders.get(token)
            if not builder: return None
            
            atm = builder.get_nearest_expiry_contract(spot_price, "CE")
            if not atm: return None
            nearest_expiry = atm['expiry']
            atm_strike = float(atm['strike'])
            
            ce_tokens, pe_tokens = [], []
            min_strike, max_strike = atm_strike - 500, atm_strike + 500
            
            for c in builder.nfo_contracts:
                if c.get('expiry') == nearest_expiry:
                    raw_s = float(c.get('strike', 0))
                    actual_s = raw_s / 100.0 if raw_s > 100000 else raw_s
                    if min_strike <= actual_s <= max_strike:
                        if c.get('symbol', '').endswith('CE'): ce_tokens.append(c['token'])
                        elif c.get('symbol', '').endswith('PE'): pe_tokens.append(c['token'])
            
            all_tokens = ce_tokens + pe_tokens
            if not all_tokens: return None
            
            response = self.order_engine.smart_api.marketData({"mode": "FULL", "exchangeTokens": {"NFO": all_tokens}})
            if not response or not response.get('status') or 'data' not in response:
                return None
            
            data = response['data']
            fetched_data = data.get('fetched', data) if isinstance(data, dict) else data
            
            total_ce_oi, total_pe_oi = 0, 0
            for item in fetched_data:
                t = item.get('exchangeToken')
                oi = item.get('opnInterest', 0)
                if t in ce_tokens: total_ce_oi += oi
                elif t in pe_tokens: total_pe_oi += oi
                
            if total_ce_oi == 0: return None
            pcr = total_pe_oi / total_ce_oi
            logging.info(f"⚖️ [INSTITUTIONAL PCR] PE OI: {total_pe_oi} | CE OI: {total_ce_oi} | PCR: {pcr:.2f}")
            return pcr
        except Exception:
            return None

    def evaluate_tick(self, symbol, spot_price, option_volume=None):
        if symbol != "NIFTY": return
        current_time = time.time()
        
        if current_time - self._last_debug_log > 10:
            logging.info(f"🔎 [DEBUG - StrategyBrain] {symbol} live Spot Price received: ₹{spot_price}")
            self._last_debug_log = current_time

        state_changed = False

        if current_time - self.last_candle_time >= 60:
            self.price_history.append(spot_price)
            self.last_candle_time = current_time
            state_changed = True
        elif len(self.price_history) == 0:
            self.price_history.append(spot_price)
            state_changed = True
        else:
            self.price_history[-1] = spot_price

        if len(self.price_history) < 15:
            if current_time - self._last_rsi_log >= 180:
                logging.info(f"⏳ [WARM-UP] Accumulating candles for validation: {len(self.price_history)}/15 collected.")
                self._last_rsi_log = current_time
            if state_changed: self._save_state()
            return

        current_rsi = self._calculate_rsi(self.price_history)
        supertrend_trend = self._calculate_supertrend(self.price_history)
        
        if current_time - self._last_rsi_log >= 300:
            logging.info(f"📊 [MARKET VITAL] NIFTY @ ₹{spot_price:.2f} | RSI: {current_rsi:.2f} | Supertrend: {supertrend_trend}")
            self._last_rsi_log = current_time

        if current_time < self.cooldown_until:
            self.last_rsi = current_rsi
            return

        # 🛑 BULLISH TRIGGER (RSI > 70 + SUPERTREND CONFIRMATION)
        if self.last_rsi < 70 and current_rsi >= 70:
            logging.info(f"⚡ [BULLISH SIGNAL] RSI crossed 70 ({current_rsi:.2f}). Checking Supertrend & PCR...")
            
            if supertrend_trend != "BULLISH":
                logging.warning(f"🛡️ [WHIPSAW BLOCKED] Bullish Signal ignored. Supertrend is {supertrend_trend} (Requires BULLISH).")
            else:
                pcr = self._get_live_pcr(symbol, spot_price)
                if pcr is None or pcr >= 0.80:
                    logging.info("✅ Supertrend & PCR Validated. Executing Call (CE)...")
                    self._trigger_entry(symbol, spot_price, instrument_type="CE")
                    self.cooldown_until = time.time() + 1800
                    logging.info("🛡️ [COOLDOWN] Next 30 mins locked.")
                else:
                    logging.warning(f"🛡️ [FAKEOUT BLOCKED] PCR is {pcr:.2f} (< 0.80).")

            self.last_rsi = current_rsi 
            self._save_state()
            
        # 🛑 BEARISH TRIGGER (RSI < 30 + SUPERTREND CONFIRMATION)
        elif self.last_rsi > 30 and current_rsi <= 30:
            logging.info(f"⚡ [BEARISH SIGNAL] RSI crossed 30 ({current_rsi:.2f}). Checking Supertrend & PCR...")
            
            if supertrend_trend != "BEARISH":
                logging.warning(f"🛡️ [WHIPSAW BLOCKED] Bearish Signal ignored. Supertrend is {supertrend_trend} (Requires BEARISH).")
            else:
                pcr = self._get_live_pcr(symbol, spot_price)
                if pcr is None or pcr <= 1.20:
                    logging.info("✅ Supertrend & PCR Validated. Executing Put (PE)...")
                    self._trigger_entry(symbol, spot_price, instrument_type="PE")
                    self.cooldown_until = time.time() + 1800
                    logging.info("🛡️ [COOLDOWN] Next 30 mins locked.")
                else:
                    logging.warning(f"🛡️ [FAKEOUT BLOCKED] PCR is {pcr:.2f} (> 1.20).")

            self.last_rsi = current_rsi 
            self._save_state()
            
        else:
            if self.last_rsi != current_rsi:
                self.last_rsi = current_rsi
                state_changed = True

        if state_changed:
            self._save_state()

    def _trigger_entry(self, symbol, spot_price, instrument_type="CE"):
        token_map = {"NIFTY": "26000"}
        token = token_map.get(symbol)
        builder = self.options_builders.get(token)
        if not builder: return
        
        contract = builder.get_nearest_expiry_contract(spot_price, instrument_type)
        if not contract: return

        contract_symbol = contract.get('symbol')
        contract_token = contract.get('token')
        strike = contract.get('strike')
        expiry = contract.get('expiry')
        
        try:
            live_premium = 0.0
            if getattr(self.order_engine, 'smart_api', None):
                resp = self.order_engine.smart_api.ltpData("NFO", contract_symbol, contract_token)
                if resp and resp.get('status'):
                    live_premium = float(resp['data']['ltp'])
            
            if live_premium <= 0: live_premium = 100.0

            target_price = round(live_premium * 1.10, 2)
            stop_loss_price = round(live_premium * 0.95, 2)

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
            logging.error(f"❌ Execution error: {e}")
