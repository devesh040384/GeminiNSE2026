import time
import logging

class OrderExecutionEngine:
    def __init__(self, smart_api, db_manager, scrip_master=None, paper_trading=True, **kwargs):
        self.smart_api = smart_api
        self.db_manager = db_manager
        self.scrip_master = scrip_master
        self.paper_trading = paper_trading

    def execute_order(self, symbol, token, qty, trans_type="BUY", exchange="NFO", 
                      order_type="MARKET", product_type="CARRYFORWARD", price=0.0, 
                      target_price=0.0, stop_loss_price=0.0):
        """
        Builds the order payload, handles API rate limits via exponential backoff, 
        and logs successful entries to the local database.
        """
        
        logging.info(f"⚙️ Preparing to {trans_type} {qty}x {symbol} ({exchange}) | Paper Trading: {self.paper_trading}")

        # 1. PAPER TRADING MODE
        if self.paper_trading:
            time.sleep(0.1)
            mock_order_id = f"mock_{int(time.time())}"
            
            # 🛡️ FAILSAFE: If price is 0.0, actively fetch the real LTP from the market
            if price <= 0.0:
                try:
                    ltp_resp = self.smart_api.ltpData(exchange, symbol, str(token))
                    if ltp_resp and ltp_resp.get("status") and ltp_resp.get("data"):
                        price = float(ltp_resp["data"]["ltp"])
                except Exception as e:
                    logging.error(f"❌ Could not fetch fallback LTP for {symbol}: {e}")

            entry_price = price if price > 0 else 0.0
            
            logging.info(f"✅ [PAPER TRADE] Successfully executed {trans_type} for {symbol} @ ₹{entry_price}. ID: {mock_order_id}")
            self.db_manager.log_trade(symbol, token, entry_price, target_price, stop_loss_price)
            return mock_order_id

        # 2. LIVE TRADING MODE (REAL MONEY)
        order_params = {
            "variety": "NORMAL",
            "tradingsymbol": symbol,
            "symboltoken": str(token),
            "transactiontype": trans_type,
            "exchange": exchange,
            "ordertype": order_type,
            "producttype": product_type,
            "duration": "DAY",
            "price": price if order_type == "LIMIT" else 0,
            "quantity": qty
        }

        try:
            # Exponential backoff for API rate limits
            retries = 3
            for attempt in range(retries):
                try:
                    order_id = self.smart_api.placeOrder(order_params)
                    if order_id:
                        logging.info(f"✅ [LIVE TRADE] Order Placed: {symbol} | ID: {order_id}")
                        
                        # 🛡️ FAILSAFE: Fetch exact entry price for market orders
                        entry_price = price
                        if order_type == "MARKET" or entry_price <= 0.0:
                            try:
                                ltp_resp = self.smart_api.ltpData(exchange, symbol, str(token))
                                if ltp_resp and ltp_resp.get("status") and ltp_resp.get("data"):
                                    entry_price = float(ltp_resp["data"]["ltp"])
                            except Exception:
                                pass
                        
                        self.db_manager.log_trade(symbol, token, entry_price, target_price, stop_loss_price)
                        return order_id
                        
                except Exception as e:
                    if "rate limit" in str(e).lower():
                        logging.warning(f"⚠️ Rate limit hit. Retrying in {2 ** attempt}s...")
                        time.sleep(2 ** attempt)
                    else:
                        raise e
                        
            logging.error(f"❌ Failed to place live order for {symbol} after {retries} attempts.")
            return None
            
        except Exception as e:
            logging.error(f"❌ Live Order Execution Error for {symbol}: {e}")
            return None
