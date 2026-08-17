import logging
import time
import threading
from datetime import datetime, timedelta

class TrailingStopLossMonitor(threading.Thread):
    def __init__(self, db_manager, smart_api=None, interval=5):
        super().__init__()
        self.db = db_manager
        self.smart_api = smart_api
        self.interval = interval
        self.daemon = True
        self._running = True

    def run(self):
        logging.info("🛡️ [TrailingStopLossMonitor] Background thread started.")
        while self._running:
            try:
                self.check_and_update_stops()
            except Exception as e:
                logging.error(f"❌ Error in TrailingStopLossMonitor loop: {e}")
            time.sleep(self.interval)

    def check_and_update_stops(self):
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, symbol, token, entry_price, target_price, stop_loss_price, peak_price 
                FROM trades WHERE status = 'OPEN'
            """)
            open_trades = cursor.fetchall()
            conn.close()

            if not open_trades:
                return

            for trade in open_trades:
                trade_id, symbol, token, entry_price, target_price, sl_price, peak_price = trade
                
                current_price = entry_price
                if self.smart_api and token:
                    try:
                        #resp = self.smart_api.ltpData("NFO", symbol, token)
                        # Dynamically select BFO for Sensex, and NFO for Nifty/BankNifty
                        trade_exchange = "BFO" if str(symbol).startswith("SENSEX") else "NFO"
                        resp = self.smart_api.ltpData(trade_exchange, symbol, token)
                        if resp and resp.get('status'):
                            current_price = float(resp['data']['ltp'])
                    except Exception:
                        continue

                # Check for Target or Stop Loss hit
                if current_price >= target_price:
                    self.close_trade(trade_id, symbol, current_price, "TARGET_HIT")
                elif current_price <= sl_price:
                    self.close_trade(trade_id, symbol, current_price, "STOP_LOSS_HIT")
                else:
                    # Trailing logic: if price climbs, trail peak and raise SL
                    if current_price > peak_price:
                        new_peak = current_price
                        new_sl = sl_price
                        # Trail stop-loss if price moves significantly higher
                        if current_price >= entry_price * 1.05:
                            new_sl = max(sl_price, entry_price) # Lock in breakeven
                        
                        conn = self.db.get_connection()
                        cursor = conn.cursor()
                        cursor.execute("""
                            UPDATE trades SET peak_price = ?, stop_loss_price = ? WHERE id = ?
                        """, (new_peak, new_sl, trade_id))
                        conn.commit()
                        conn.close()
        except Exception as e:
            logging.error(f"❌ Failed checking/updating stop losses: {e}")

    def close_trade(self, trade_id, symbol, exit_price, reason):
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            ist_time = (datetime.utcnow() + timedelta(hours=5, minutes=30)).strftime('%Y-%m-%d %H:%M:%S')
            cursor.execute("""
                UPDATE trades SET status = 'CLOSED', exit_price = ?, exit_time = ?, exit_reason = ? WHERE id = ?
            """, (exit_price, ist_time, reason, trade_id))
            conn.commit()
            conn.close()
            logging.info(f"🏁 [TRADE CLOSED] {symbol} | Exit ₹{exit_price:.2f} | Reason: {reason}")
        except Exception as e:
            logging.error(f"❌ Failed to close trade ID {trade_id}: {e}")

    def stop(self):
        self._running = False


class TradeReconciler:
    def __init__(self, smart_api, db_manager):
        self.smart_api = smart_api
        self.db = db_manager

    def reconcile(self):
        """Reconciles database open positions with active broker positions on startup."""
        try:
            if not self.smart_api:
                return
            
            positions_resp = self.smart_api.position()
            if not positions_resp or not positions_resp.get('status'):
                return

            # Safely handle None or empty data responses to prevent iteration errors
            broker_data = positions_resp.get('data')
            if not broker_data:
                return

            active_symbols = {p.get('tradingsymbol') for p in broker_data if float(p.get('netqty', 0)) != 0}

            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT id, symbol FROM trades WHERE status = 'OPEN'")
            db_trades = cursor.fetchall()

            for trade_id, symbol in db_trades:
                if symbol not in active_symbols:
                    # If trade is marked OPEN in DB but not active at broker, mark closed
                    ist_time = (datetime.utcnow() + timedelta(hours=5, minutes=30)).strftime('%Y-%m-%d %H:%M:%S')
                    cursor.execute("""
                        UPDATE trades SET status = 'CLOSED', exit_time = ?, exit_reason = 'RECONCILED_CLOSED' WHERE id = ?
                    """, (ist_time, trade_id))
                    logging.warning(f"⚠️ [RECONCILIATION] Trade {symbol} (ID: {trade_id}) was closed externally at broker. Updated DB.")

            conn.commit()
            conn.close()
        except Exception as e:
            logging.error(f"❌ Error during trade reconciliation: {e}")
