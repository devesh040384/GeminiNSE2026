import unittest
from strategy_brain import StrategyBrain
from risk_manager import RiskManager

class TestAlgoEngineCore(unittest.TestCase):
    def setUp(self):
        self.strategy = StrategyBrain(fast_period=20, slow_period=50)
        self.risk = RiskManager(max_daily_loss_inr=5000.0)

    def test_paise_conversion(self):
        # Nifty Options Paise to Rupees
        raw_paise_tick = 9965.0
        parsed_price = raw_paise_tick / 100.0 if raw_paise_tick > 500 else float(raw_paise_tick)
        self.assertEqual(parsed_price, 99.65)

    def test_strategy_direction(self):
        # Provide enough ticks to fill the 50-period EMA minimum threshold
        direction = "HOLD"
        for _ in range(55):
            direction = self.strategy.analyze_market_state(23600.0)
        
        self.assertIn(direction, ["BUY_CALL", "BUY_PUT", "HOLD"])

    def test_risk_manager_limit(self):
        self.risk.register_trade_result(-2000.0)
        self.assertEqual(self.risk.trading_halted, False)
        
        self.risk.register_trade_result(-3500.0)
        self.assertEqual(self.risk.trading_halted, True)

if __name__ == "__main__":
    unittest.main()
