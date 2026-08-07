# config.py - Centralized configuration for Multi-Index F&O Trading

# Execution Mode Flag (True = Paper Trading, False = Live Broker Execution)
PAPER_TRADING = True

# Active Indices Monitored by the Bot
#ACTIVE_INDICES = ["NIFTY"]  # Add "BANKNIFTY" or "SENSEX" when ready
#ACTIVE_INDICES = ["NIFTY", "BANKNIFTY", "SENSEX"]
ACTIVE_INDICES = ["NIFTY", "SENSEX"]


INDICES_CONFIG = {
    "NIFTY": {
        "index_token": "26000",
        "exchange": "NFO",
        "exchange_type": 1,
        "lot_size": 65,
        "choppy_range_threshold": 35.0,
        "trending_target_mult": 1.10,
        "trending_sl_mult": 0.95,
        "choppy_target_mult": 1.06,
        "choppy_sl_mult": 0.97
    },
    "BANKNIFTY": {
        "index_token": "99926009",      # Replace with your actual Bank Nifty index token from scrip_master.json
        "exchange": "NFO",
        "exchange_type": 1,
        "lot_size": 15,
        "choppy_range_threshold": 150.0,
        "trending_target_mult": 1.12,
        "trending_sl_mult": 0.94,
        "choppy_target_mult": 1.07,
        "choppy_sl_mult": 0.96
    },
    "SENSEX": {
        "index_token": "99919000",      # Replace with your actual Sensex index token from scrip_master.json
        "exchange": "BFO",
        "exchange_type": 3,             # Exchange type 3 or 5 for BSE derivatives
        "lot_size": 10,
        "choppy_range_threshold": 120.0,
        "trending_target_mult": 1.10,
        "trending_sl_mult": 0.95,
        "choppy_target_mult": 1.06,
        "choppy_sl_mult": 0.97
    }
}
