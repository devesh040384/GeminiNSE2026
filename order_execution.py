import logging
import database

class OrderExecutionEngine:
    def __init__(self, smart_api=None, db_manager=None, paper_trading=True, **kwargs):
        self.smart_api = smart_api
        self.db_manager = db_manager
        self.paper_trading = paper_trading
        # Ensure database schema is initialised upon startup
        #database.init_db()
        if hasattr(database, 'migrate_database_schema'):
            database.migrate_database_schema()

    def execute_options_order(self, symbol, strike, entry_price, target_price=0.0, stop_loss_price=0.0, token="", qty=65, quantity=65, action="BUY", instrument_type="CE", entry_spot=0.0, **kwargs):
        """
        Executes or simulates an options trade.
        Consolidates 'qty' and 'quantity' kwargs to ensure the lot size never defaults to 0.
        """
        # Resolve quantity from any kwarg passed by StrategyBrain
        final_qty = qty if (qty and qty > 0) else (quantity if (quantity and quantity > 0) else 65)

        logging.info(
            f"📋 [PAPER ORDER EXECUTED] Symbol: {symbol} | Strike: {strike} | "
            f"Qty: {final_qty} | Entry Premium: ₹{entry_price:.2f} | "
            f"Target Premium: ₹{target_price:.2f} | SL Premium: ₹{stop_loss_price:.2f}"
        )

        if self.paper_trading:
            trade_id = database.log_paper_order(
                symbol=symbol,
                token=token,
                action=action,
                qty=final_qty,
                quantity=final_qty,
                entry_price=entry_price,
                target_spot=target_price,
                stop_spot=stop_loss_price,
                instrument_type=instrument_type,
                strike=strike,
                entry_spot=entry_spot
            )
            return trade_id
        else:
            # Place real market order via Angel One SmartAPI here when live
            logging.info(f"⚡ [LIVE BROKER ORDER] Placing live market order for {symbol} via SmartAPI...")
            return None
