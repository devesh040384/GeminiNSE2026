import time
import json
import os
import logging
from datetime import datetime, timedelta
from config import INDICES_CONFIG

class StrategyBrain:
    def __init__(self, order_manager=None, order_engine=None, **kwargs):
        self.order_manager = order_manager or order_engine
        self.options_builders = kwargs.get("options_builders", {})
        
        self.price_histories = {symbol: [] for symbol in INDICES_CONFIG.keys()}
        self.rsi_histories = {symbol: [] for symbol in INDICES_CONFIG.keys()}
        self.last_candle_times = {symbol: 0.0 for symbol in INDICES_CONFIG.keys()}
        self._last_debug_logs = {symbol: 0.0 for symbol in INDICES_CONFIG.keys()}
        self._last_rsi_logs = {symbol: 0.0 for symbol in INDICES_CONFIG.keys()}
        self.cooldown_until = {symbol: 0.0 for symbol in INDICES_CONFIG.keys()}
        self.last_arsis = {symbol: 50.0 for symbol in INDICES_CONFIG.keys()}
        self.current_regimes = {symbol: "INITIALIZING" for symbol in INDICES_CONFIG.keys()}
        
        self.circuit_breaker_tripped = False
        
        self.state_file = "rsi_state.json"
        self._load_state()

    def _calculate_rsi(self, prices, period=14):
        if len(prices) < period + 1:
            return 50.0
        gains = []
        losses = []
        for i in range(1, len(prices)):
            change = prices[i] - prices[i-1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))
        
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        
        if avg_gain == 0 and avg_loss == 0: return 50.0
        if avg_loss == 0: return 100.0
            
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def _calculate_ema(self, history, period):
        if len(history) < period:
            return sum(history) / len(history) if history else 0.0
        multiplier = 2 / (period + 1)
        ema = sum(history[:period]) / period
        for price in history[period:]:
            ema = (price - ema) * multiplier + ema
        return ema

    def _save_state(self):
        try:
            today_str = datetime.now().strftime("%Y-%m-%d")
            with open(self.state_file, "w") as f:
                json.dump({
                    "date": today_str,
                    "price_histories": self.price_histories,
                    "last_arsis": self.last_arsis,
                    "last_candle_times": self.last_candle_times
                }, f)
        except Exception as e:
            logging.error(f"❌ Error saving StrategyBrain state: {e}")

    def _load_state(self):
        if os.path.exists(self.state_file):
            try:
                today_str = datetime.now().strftime("%Y-%m-%d")
                with open(self.state_file, "r") as f:
                    state = json.load(f)
                    if state.get("date", "") == today_str:
                        loaded_histories = state.get("price_histories", {})
                        for symbol in INDICES_CONFIG.keys():
                            if symbol in loaded_histories:
                                self.price_histories[symbol] = loaded_histories[symbol]
                        self.last_arsis = state.get("last_arsis", self.last_arsis)
                        self.last_candle_times = state.get("last_candle_times", self.last_candle_times)
            except Exception as e:
                logging.error(f"❌ Error loading StrategyBrain state: {e}")

    def _check_circuit_breaker(self):
        if self.circuit_breaker_tripped: return True
        try:
            import sqlite3
            conn = sqlite3.connect('trade_history.db')
            cursor = conn.cursor()
            today = datetime.now().strftime("%Y-%m-%d")
            
            # FIX: Removed 'qty' from SELECT query
            cursor.execute('''
                SELECT symbol, entry_price, exit_price 
                FROM trades 
                WHERE status = 'CLOSED' AND entry_time LIKE ? 
                ORDER BY exit_time ASC
            ''', (f"{today}%",))
            
            trades = cursor.fetchall()
            conn.close()
            
            daily_pnl = 0.0
            consecutive_losses = 0
            
            for trade in trades:
                sym, entry, exit_p = trade
                # FIX: Calculate qty dynamically
                actual_qty = 25 if "NIFTY" in sym.upper() else 10
                
                pnl = (exit_p - entry) * actual_qty
                daily_pnl += pnl
                
                if pnl < 0:
                    consecutive_losses += 1
                else:
                    consecutive_losses = 0
                    
            if daily_pnl <= -2000.00:
                logging.critical(f"🛑 CIRCUIT BREAKER! Daily Loss (₹{daily_pnl:.2f}) hit. Halting entries.")
                self.circuit_breaker_tripped = True
                return True
            if consecutive_losses >= 5:
                logging.critical(f"🛑 CIRCUIT BREAKER! 5 consecutive losses. Market toxic. Halting entries.")
                self.circuit_breaker_tripped = True
                return True
            return False
        except Exception as e:
            logging.error(f"⚠️ Error checking circuit breaker: {e}")
            return False

    def _trigger_entry(self, symbol, spot_price, option_type, target_mult, sl_mult):
        try:
            if self._check_circuit_breaker(): return False
            if not self.order_manager: return False

            config = INDICES_CONFIG.get(symbol, {})
            index_token = str(config.get("index_token"))
            
            builder = self.options_builders.get(index_token)
            if not builder: return False

            contract = builder.get_nearest_expiry_contract(spot_price, instrument_type=option_type)
            if not contract: return False

            opt_symbol = contract.get("symbol")
            opt_token = str(contract.get("token"))
            exchange = "BFO" if symbol == "SENSEX" else "NFO"
            qty = int(contract.get("lotsize", 25 if symbol == "NIFTY" else 10))

            try:
                ltp_resp = self.order_manager.smart_api.ltpData(exchange, opt_symbol, opt_token)
                if ltp_resp and ltp_resp.get("status") and ltp_resp.get("data"):
                    opt_ltp = float(ltp_resp["data"]["ltp"])
                else: return False
                    
                target_price = round(opt_ltp * target_mult, 1)
                sl_price = round(opt_ltp * sl_mult, 1)
                logging.info(f"🎯 [{symbol}] Executing Sniper Entry: {opt_symbol} @ ₹{opt_ltp} | Target: ₹{target_price} | SL: ₹{sl_price}")
            except Exception as e:
                return False

            self.order_manager.execute_order(
                symbol=opt_symbol, token=opt_token, qty=qty, trans_type="BUY",
                exchange=exchange, price=opt_ltp, target_price=target_price, stop_loss_price=sl_price
            )
            return True
        except Exception:
            return False

    def evaluate_tick(self, symbol, spot_price, option_volume=None):
        if symbol not in INDICES_CONFIG: return
        current_time = time.time()
        
        now_ist = datetime.utcnow() + timedelta(hours=5, minutes=30)
        current_hour_min = now_ist.hour * 100 + now_ist.minute

        history = self.price_histories.get(symbol, [])
        state_changed = False

        last_candle_time = self.last_candle_times.get(symbol, 0.0)
        if current_time - last_candle_time >= 60:
            history.append(spot_price)
            if len(history) > 375: history.pop(0)
            self.last_candle_times[symbol] = current_time
            state_changed = True
        elif len(history) == 0:
            history.append(spot_price)
            self.last_candle_times[symbol] = current_time
            state_changed = True
        else:
            history[-1] = spot_price

        self.price_histories[symbol] = history
        
        if len(history) < 21:
            if state_changed: self._save_state()
            return

        current_rsi = self._calculate_rsi(history)
        
        if symbol not in self.rsi_histories: self.rsi_histories[symbol] = []
        self.rsi_histories[symbol].append(current_rsi)
        if len(self.rsi_histories[symbol]) > 5:
            self.rsi_histories[symbol].pop(0)
            
        ema_9 = self._calculate_ema(history, 9)
        ema_21 = self._calculate_ema(history, 21)
        vwap = sum(history) / len(history)

        # VWAP & EMA SNIPER FILTERS
        vwap_buffer = 10.0 if symbol == "NIFTY" else 30.0
        ema_spread_min = 5.0 if symbol == "NIFTY" else 15.0

        if ema_9 > (ema_21 + ema_spread_min) and spot_price > (vwap + vwap_buffer):
            macro_trend = "BULLISH"
        elif ema_9 < (ema_21 - ema_spread_min) and spot_price < (vwap - vwap_buffer):
            macro_trend = "BEARISH"
        else:
            macro_trend = "CHOPPY"
            
        self.current_regimes[symbol] = macro_trend

        # Strict Execution Window
        if current_hour_min < 945 or current_hour_min > 1515:
            if state_changed: self._save_state()
            return

        if current_time < self.cooldown_until.get(symbol, 0.0):
            self.last_arsis[symbol] = current_rsi
            return

        last_rsi = self.last_arsis.get(symbol, 50.0)
        config = INDICES_CONFIG[symbol]
        
        recent_rsis = self.rsi_histories[symbol]
        rsi_dipped_bullish = any(r < 45 for r in recent_rsis)
        rsi_spiked_bearish = any(r > 55 for r in recent_rsis)

        if macro_trend == "BULLISH":
            if last_rsi < 50 and current_rsi >= 50 and rsi_dipped_bullish:
                logging.info(f"⚡ [{symbol} CONFIRMED BREAKOUT] Trend UP. Clean RSI Hook. Buying CE...")
                if self._trigger_entry(symbol, spot_price, "CE", config["trending_target_mult"], config["trending_sl_mult"]):
                    self.cooldown_until[symbol] = time.time() + 900
                
        elif macro_trend == "BEARISH":
            if last_rsi > 50 and current_rsi <= 50 and rsi_spiked_bearish:
                logging.info(f"⚡ [{symbol} CONFIRMED BREAKDOWN] Trend DOWN. Clean RSI Hook. Buying PE...")
                if self._trigger_entry(symbol, spot_price, "PE", config["trending_target_mult"], config["trending_sl_mult"]):
                    self.cooldown_until[symbol] = time.time() + 900
                
        elif macro_trend == "CHOPPY":
            if last_rsi < 80 and current_rsi >= 80:
                logging.info(f"⚡ [{symbol} CHOPPY OVERBOUGHT] Price rejected at top. Scalping PE...")
                if self._trigger_entry(symbol, spot_price, "PE", config["choppy_target_mult"], config["choppy_sl_mult"]):
                    self.cooldown_until[symbol] = time.time() + 1800
            elif last_rsi > 20 and current_rsi <= 20:
                logging.info(f"⚡ [{symbol} CHOPPY OVERSOLD] Price rejected at bottom. Scalping CE...")
                if self._trigger_entry(symbol, spot_price, "CE", config["choppy_target_mult"], config["choppy_sl_mult"]):
                    self.cooldown_until[symbol] = time.time() + 1800

        if last_rsi != current_rsi:
            self.last_arsis[symbol] = current_rsi
            state_changed = True

        if state_changed:
            self._save_state()
