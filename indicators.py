import numpy as np

class TechnicalIndicators:
    @staticmethod
    def calculate_atr(highs, lows, closes, period=14):
        """Calculates Average True Range (ATR) for volatility filtering."""
        if len(closes) < period + 1:
            return 0.0
        
        tr_list = []
        for i in range(1, len(closes)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1])
            )
            tr_list.append(tr)
            
        return float(np.mean(tr_list[-period:]))

    @staticmethod
    def calculate_rsi(closes, period=14):
        """Calculates Relative Strength Index (RSI)."""
        if len(closes) < period + 1:
            return 50.0 # Neutral default
            
        deltas = np.diff(closes)
        seed = deltas[:period]
        up = seed[seed >= 0].sum() / period
        down = -seed[seed < 0].sum() / period
        
        if down == 0:
            return 100.0
            
        rs = up / down
        rsi = 100.0 - (100.0 / (1.0 + rs))
        return float(rsi)

    @staticmethod
    def calculate_vwap(prices, volumes):
        """Calculates Volume-Weighted Average Price (VWAP)."""
        if len(prices) == 0 or len(volumes) == 0:
            return prices[-1] if prices else 0.0
            
        p = np.array(prices)
        v = np.array(volumes)
        return float(np.sum(p * v) / np.sum(v)) if np.sum(v) > 0 else float(p[-1])

    @staticmethod
    def calculate_bbw(closes, period=20, num_std=2):
        """Calculates Bollinger Band Width (BBW) to detect volatility squeezes."""
        if len(closes) < period:
            return 0.0
            
        recent_closes = np.array(closes[-period:])
        sma = np.mean(recent_closes)
        std = np.std(recent_closes)
        
        upper = sma + (num_std * std)
        lower = sma - (num_std * std)
        
        if sma == 0:
            return 0.0
            
        return float((upper - lower) / sma)
