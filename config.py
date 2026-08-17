# config.py

# Active Indices Selection
ACTIVE_INDICES = ["NIFTY", "SENSEX"]

# Paper Trading Mode (Set to False for Live Broker Execution)
PAPER_TRADING = True

# Individual Index Configurations & Risk Parameters
INDICES_CONFIG = {
    "NIFTY": {
        "token": "26000",
        "index_token": "26000",
        "exchange": "NSE",
        "symbol": "NIFTY",
        
        # 📈 TRENDING REGIME (The Home Run Hitter)
        "trending_sl_mult": 0.85,      # 15% Stop Loss
        "trending_target_mult": 1.50,  # 50% Target
        
        # 🔪 CHOPPY REGIME (The Micro-Scalper)
        "choppy_sl_mult": 0.95,        # 5% Stop Loss (Eject immediately on weakness)
        "choppy_target_mult": 1.08,    # 8% Target (Quick profit taking before reversal)
    },
    "SENSEX": {
        "token": "99919000",
        "index_token": "99919000",
        "exchange": "BSE",
        "symbol": "SENSEX",
        
        # 📈 TRENDING REGIME
        "trending_sl_mult": 0.85,      # 15% Stop Loss
        "trending_target_mult": 1.50,  # 50% Target
        
        # 🔪 CHOPPY REGIME
        "choppy_sl_mult": 0.95,        # 5% Stop Loss (Eject immediately on weakness)
        "choppy_target_mult": 1.08,    # 8% Target (Quick profit taking before reversal)
    }
}
