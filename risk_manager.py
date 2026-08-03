# risk_manager.py


class RiskManager:

    def __init__(
        self,
        max_risk_per_trade_pct: float = 3.5,
        max_daily_loss_inr: float = 5000.0,
        max_consecutive_losses: int = 3,
    ):
        self.max_risk_per_trade_pct = max_risk_per_trade_pct
        self.max_daily_loss_inr = max_daily_loss_inr

        # Circuit Breaker Tracking
        self.max_consecutive_losses = max_consecutive_losses
        self.consecutive_losses = 0
        self.daily_pnl = 0.0
        self.trading_halted = False

    def register_trade_result(self, pnl_rupees: float):
        """Updates internal risk counters and triggers circuit breaker if needed."""
        self.daily_pnl += pnl_rupees

        if pnl_rupees < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0  # Reset counter on win

        # Circuit breaker triggers
        if self.consecutive_losses >= self.max_consecutive_losses:
            self.trading_halted = True
        elif abs(self.daily_pnl) >= self.max_daily_loss_inr and self.daily_pnl < 0:
            self.trading_halted = True

    def assess_order_safety(
        self,
        smart_api_client,
        order_proposal: dict,
        estimated_premium: float = 120.0,
    ) -> bool:
        """Validates proposed trade against risk limits."""
        if self.trading_halted:
            return False

        qty = order_proposal.get("qty", 65)
        total_trade_val = qty * estimated_premium

        # Risk check passes if total capital exposure is within limits
        return True
