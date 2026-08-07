import logging
import time
import collections
import pandas as pd
from datetime import datetime, timedelta
import json
import os
from config import INDICES_CONFIG
from indicators import TechnicalIndicators

class StrategyBrain:
    def __init__(self, order_engine, options_builders, scrip_master_data=None):
        self.order_engine = order_engine
        self.options_builders = options_builders
        self.scrip_master_data = scrip_master_data
        
        self.price_histories = {symbol: collections.deque(maxlen=60) for symbol in INDICES_CONFIG.keys()}
        self.last_arsis = {symbol: 50.0 for symbol in INDICES_CONFIG.keys()}
        
        self.last_candle_time = time.time()
        self._last_debug_log = 0
        self._last_rsi_log = 0
        
        self.cooldown_until = {} 
        self.contract_cooldowns = {} 
        self.state_file = "rsi_state.json"
        self._load_state()

    def _load_state(self):
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    saved_history = data.get('price_histories', {})
                    for sym, hist in saved_history.items():
                        if sym in self.price_histories:
                            self.price_histories[sym].extend(hist)
                    self.last_arsis = data.get('last_arsis', self.last_arsis)
                    
                    saved_cooldowns = data.get('contract_cooldowns', {})
                    current_time = time.time()
                    self.contract_cooldowns = {sym: expiry for sym, expiry in saved_cooldowns.items() if expiry > current_time}
                    
                logging.info(f"💾 [STATE RECOVERED] Active Strike Cooldowns: {len(self.contract_cooldowns)}")
            except Exception as e:
                logging.error(f"❌ Failed to load state: {e}")

    def _save_state(self):
        try:
            data = {
                'price_histories': {sym: list(hist) for sym, hist in self.price_histories.items()}, 
                'last_arsis': self.last_arsis,
                'contract_cooldowns': self.contract_cooldowns
            }
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(data, f)
        except Exception as e:
            logging.error(f"❌ Failed to save state: {e}")

    def _calculate_rsi(self, prices, period=14):
        """Delegates to modular TechnicalIndicators for robust RSI computation."""
        return TechnicalIndicators.calculate_rsi(list(prices), period=period)

    def _calculate_atr(self, prices, period=14):
        """Calculates ATR using rolling pseudo highs/lows from historical spot prices."""
        if len(prices) < period + 1:
            return 0.0
        p_list = list(prices)
        highs = [p + 2.0 for p in p_list]
        lows = [p - 2.0 for p in p_list]
        return TechnicalIndicators.calculate_atr(highs, lows, p_list, period=period)

    def _calculate_supertrend(self, prices, period=10, multiplier=3.0):
        if len(prices) < period + 5:
            return "NEUTRAL"
        try:
            df = pd.DataFrame({'close': list(prices)})
            df['high'] = df['close'] + 2.0 
            df['low'] = df['close'] - 2.0
            
            df['tr1'] = df['high'] - df['low']
            df['tr2'] = abs(df['high'] - df['close'].shift(1))
            df['tr3'] = abs(df['low'] - df['close'].shift(1))
            df['tr'] = df[['tr1', 'tr2', 'tr3']].max(axis=1)
            df['atr'] = df['tr'].rolling(window=period).mean()
            
            hl2 = (df['high'] + df['low']) / 2
            df['upperband'] = hl2 + (multiplier * df['atr'])
            df['lowerband'] = hl2 - (multiplier * df['atr'])
            
            current_close = df['close'].iloc[-1]
            current_sma = df['close'].rolling(window=period).mean().iloc[-1]
            
            return "BULLISH" if current_close > current_sma else "BEARISH"
        except Exception:
            return "NEUTRAL"

    def _detect_market_regime(self, symbol, history):
        config = INDICES_CONFIG.get(symbol, INDICES_CONFIG["NIFTY"])
        threshold = config["choppy_range_threshold"]
        
        if len(history) < 30:
            return "TRENDING"
        
        s = pd.Series(list(history))
        recent_range = s.tail(30).max() - s.tail(30).min()
        
        if recent_range < threshold:
            return "CHOPPY"
        return "TRENDING"

    def _get_live_pcr(self, symbol, spot_price):
        try:
            if not getattr(self.order_engine, 'smart_api', None):
                return None
            config = INDICES_CONFIG.get(symbol, {})
            token = config.get("index_token")
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
            
            exchange = config.get("exchange", "NFO")
            response = self.order_engine.smart_api.marketData({"mode": "FULL", "exchangeTokens": {exchange: all_tokens}})
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
            return total_pe_oi / total_ce_oi
        except Exception:
            return None

    def evaluate_tick(self, symbol, spot_price, option_volume=None):
        if symbol not in INDICES_CONFIG: return
        current_time = time.time()
        
        # ⏰ 1. STRICT TIME WINDOW FILTER (09:30 AM to 02:45 PM IST)
        now_ist = datetime.utcnow() + timedelta(hours=5, minutes=30)
        current_hour_min = now_ist.hour * 100 + now_ist.minute
        
        if current_hour_min < 930 or current_hour_min > 1445:
            return  # Outside optimal trading window

        if current_time - self._last_debug_log > 15:
            logging.info(f"🔎 [DEBUG - StrategyBrain] {symbol} live Spot Price received: ₹{spot_price}")
            self._last_debug_log = current_time

        history = self.price_histories[symbol]
        state_changed = False

        if current_time - self.last_candle_time >= 60:
            history.append(spot_price)
            self.last_candle_time = current_time
            state_changed = True
        elif len(history) == 0:
            history.append(spot_price)
            state_changed = True
        else:
            history[-1] = spot_price

        if len(history) < 15:
            if current_time - self._last_rsi_log >= 180:
                logging.info(f"⏳ [{symbol} WARM-UP] Accumulating candles: {len(history)}/15 collected.")
                self._last_rsi_log = current_time
            if state_changed: self._save_state()
            return

        current_rsi = self._calculate_rsi(history)
        current_atr = self._calculate_atr(history)
        supertrend_trend = self._calculate_supertrend(history)
        market_regime = self._detect_market_regime(symbol, history)
        
        if current_time - self._last_rsi_log >= 300:
            logging.info(f"📊 [{symbol} REGIME: {market_regime}] Price: ₹{spot_price:.2f} | RSI: {current_rsi:.2f} | ATR: {current_atr:.2f}")
            self._last_rsi_log = current_time

        symbol_cooldown = self.cooldown_until.get(symbol, 0.0)
        if current_time < symbol_cooldown:
            self.last_arsis[symbol] = current_rsi
            return

        last_rsi = self.last_arsis.get(symbol, 50.0)
        config = INDICES_CONFIG[symbol]

        # ==========================================
        # 🌐 TRENDING REGIME
        # ==========================================
        if market_regime == "TRENDING":
            if last_rsi < 70 and current_rsi >= 70:
                logging.info(f"⚡ [{symbol} TRENDING BULLISH] RSI crossed 70 ({current_rsi:.2f}).")
                if supertrend_trend == "BULLISH":
                    pcr = self._get_live_pcr(symbol, spot_price)
                    if pcr is None or pcr >= 0.80:
                        if self._trigger_entry(symbol, spot_price, "CE", config["trending_target_mult"], config["trending_sl_mult"]):
                            self.cooldown_until[symbol] = time.time() + 1800
                self.last_arsis[symbol] = current_rsi 
                self._save_state()
                
            elif last_rsi > 30 and current_rsi <= 30:
                logging.info(f"⚡ [{symbol} TRENDING BEARISH] RSI crossed 30 ({current_rsi:.2f}).")
                if supertrend_trend == "BEARISH":
                    pcr = self._get_live_pcr(symbol, spot_price)
                    if pcr is None or pcr <= 1.20:
                        if self._trigger_entry(symbol, spot_price, "PE", config["trending_target_mult"], config["trending_sl_mult"]):
                            self.cooldown_until[symbol] = time.time() + 1800
                self.last_arsis[symbol] = current_rsi 
                self._save_state()

        # ==========================================
        # 🌐 CHOPPY REGIME
        # ==========================================
        elif market_regime == "CHOPPY":
            if last_rsi < 78 and current_rsi >= 78:
                logging.info(f"⚡ [{symbol} CHOPPY FADE TOP] RSI reached {current_rsi:.2f}. Buying Put (PE)...")
                if self._trigger_entry(symbol, spot_price, "PE", config["choppy_target_mult"], config["choppy_sl_mult"]):
                    self.cooldown_until[symbol] = time.time() + 1800
                self.last_arsis[symbol] = current_rsi
                self._save_state()

            elif last_rsi > 22 and current_rsi <= 22:
                logging.info(f"⚡ [{symbol} CHOPPY FADE BOTTOM] RSI reached {current_rsi:.2f}. Buying Call (CE)...")
                if self._trigger_entry(symbol, spot_price, "CE", config["choppy_target_mult"], config["choppy_sl_mult"]):
                    self.cooldown_until[symbol] = time.time() + 1800
                self.last_arsis[symbol] = current_rsi
                self._save_state()

        if last_rsi != current_rsi:
            self.last_arsis[symbol] = current_rsi
            state_changed = True

        if state_changed:
            self._save_state()

    def _trigger_entry(self, symbol, spot_price, instrument_type, target_mult, sl_mult):
        config = INDICES_CONFIG.get(symbol, {})
        token = config.get("index_token")
        builder = self.options_builders.get(token)
        if not builder: return False
        
        contract = builder.get_nearest_expiry_contract(spot_price, instrument_type)
        if not contract: return False

        contract_symbol = contract.get('symbol')
        contract_token = contract.get('token')
        strike = contract.get('strike')
        current_time = time.time()

        # ⏱️ 60-MINUTE STRIKE COOLDOWN CHECK
        if contract_symbol in self.contract_cooldowns:
            cooldown_expiry = self.contract_cooldowns[contract_symbol]
            if current_time < cooldown_expiry:
                remaining_mins = int((cooldown_expiry - current_time) / 60)
                logging.warning(f"🛡️ [STRIKE COOLDOWN] Contract {contract_symbol} is in 60-min cool-down ({remaining_mins} mins left). Skipping.")
                return False
            else:
                del self.contract_cooldowns[contract_symbol]

        try:
            live_premium = 0.0
            if getattr(self.order_engine, 'smart_api', None):
                exchange = config.get("exchange", "NFO")
                resp = self.order_engine.smart_api.ltpData(exchange, contract_symbol, contract_token)
                if resp and resp.get('status'):
                    live_premium = float(resp['data']['ltp'])
            
            if live_premium <= 0: live_premium = 100.0

            target_price = round(live_premium * target_mult, 2)
            stop_loss_price = round(live_premium * sl_mult, 2)

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
            
            self.contract_cooldowns[contract_symbol] = current_time + 3600
            self._save_state()
            logging.info(f"⏱️ [STRIKE LOCKED] {contract_symbol} placed on 60-minute cool-down timer.")
            return True
        except Exception as e:
            logging.error(f"❌ Execution error: {e}")
            return False
