import logging
from datetime import datetime, timedelta

class OrderExecutionEngine:
    def __init__(self, smart_api, db_manager, scrip_master=None, paper_trading=True):
        self.smart_api = smart_api
        self.db = db_manager
        self.scrip_master = scrip_master or []
        self.paper_trading = paper_trading
        
        mode_label = "📝 PAPER TRADING MODE"
        if not self.paper_trading:
            mode_label = "🔥 LIVE TRADING MODE (REAL MONEY)"
        logging.info(f"✅ OrderExecutionEngine initialized. Running in: {mode_label}")

    def execute_options_order(self, symbol, strike, token, entry_price, target_price, stop_loss_price, action="BUY", instrument_type="CE", entry_spot=0.0):
        """Executes and logs an options derivative order (Supports both Paper and Live execution)."""
        try:
            lot_size = 65  # Default fallback lot size if not specified
            
            # Attempt to look up precise lot size from scrip master if available
            if self.scrip_master:
                for scrip in self.scrip_master:
                    if str(scrip.get('token')) == str(token) or scrip.get('symbol') == symbol:
                        lotsize_raw = scrip.get('lotsize') or scrip.get('lot_size')
                        if lotsize_raw:
                            lot_size = int(lotsize_raw)
                            break

            if self.paper_trading:
                logging.info(f"📋 [PAPER ORDER EXECUTED] Symbol: {symbol} | Strike: {strike} | Qty: {lot_size} | Entry Premium: ₹{entry_price:.2f} | Target Premium: ₹{target_price:.2f} | SL Premium: ₹ {stop_loss_price:.2f}")
            else:
                # Live broker order placement placeholder (Angel One SmartAPI placeOrder integration)
                try:
                    orderparams = {
                        "variety": "NORMAL",
                        "tradingsymbol": symbol,
                        "symboltoken": str(token),
                        "transactiontype": action.upper(),
                        "exchange": "NFO",
                        "ordertype": "MARKET",
                        "producttype": "INTRADAY",
                        "duration": "DAY",
                        "price": "0",
                        "squareoff": "0",
                        "stoploss": "0",
                        "quantity": str(lot_size)
                    }
                    if self.smart_api:
                        order_id = self.smart_api.placeOrder(orderparams)
                        logging.info(f"🔥 [LIVE ORDER PLACED] Order ID: {order_id} | Symbol: {symbol} | Qty: {lot_size}")
                except Exception as live_err:
                    logging.error(f"❌ Broker Live Order Placement Failed: {live_err}")
                    return {"status": "FAILED", "reason": str(live_err)}

            # 🛡️ Safe database logging wrapper (Prevents execution crashes if a method name varies)
            try:
                if hasattr(self.db, 'log_paper_order'):
                    self.db.log_paper_order(
                        symbol=symbol,
                        token=token,
                        strike=strike,
                        entry_price=entry_price,
                        target_price=target_price,
                        stop_loss_price=stop_loss_price,
                        action=action,
                        instrument_type=instrument_type,
                        entry_spot=entry_spot
                    )
                elif hasattr(self.db, 'log_trade'):
                    self.db.log_trade(
                        symbol=symbol,
                        token=token,
                        strike=strike,
                        entry_price=entry_price,
                        target_price=target_price,
                        stop_loss_price=stop_loss_price,
                        action=action,
                        instrument_type=instrument_type,
                        entry_spot=entry_spot
                    )
                elif hasattr(self.db, 'log_live_order'):
                    self.db.log_live_order(
                        symbol=symbol,
                        token=token,
                        strike=strike,
                        entry_price=entry_price,
                        target_price=target_price,
                        stop_loss_price=stop_loss_price,
                        action=action,
                        instrument_type=instrument_type,
                        entry_spot=entry_spot
                    )
                else:
                    logging.warning("⚠️ [DB WARNING] Database instance missing core logging method. Trade processed in memory.")
            except Exception as db_err:
                logging.error(f"❌ Database logging exception safely bypassed: {db_err}")

            return {"status": "SUCCESS", "symbol": symbol, "entry_price": entry_price}

        except Exception as e:
            logging.error(f"❌ Critical error inside execute_options_order: {e}")
            return {"status": "ERROR", "message": str(e)}
