"""Configuration for the 5-min scalp trading bot."""

from dataclasses import dataclass, field
from typing import List


@dataclass
class TradingConfig:
    # Paper trading
    initial_balance: float = 200.0
    risk_per_trade_pct: float = 1.0  # 1% risk per trade
    max_open_trades: int = 3

    # Instruments
    forex_pairs: List[str] = field(default_factory=lambda: [
        "EURUSD=X", "GBPUSD=X", "USDJPY=X", "AUDUSD=X",
    ])
    stocks: List[str] = field(default_factory=lambda: [
        "AAPL", "MSFT", "TSLA", "AMZN", "SPY",
    ])

    # Timeframe
    interval: str = "5m"  # 5-minute candles

    # Session times (UTC)
    asian_start: str = "00:00"
    asian_end: str = "08:00"
    london_start: str = "08:00"
    london_end: str = "13:00"
    ny_start: str = "13:30"
    ny_end: str = "20:00"

    # Asian range filter — max allowed range as fraction of price
    max_asian_range_pct: float = 0.5  # 0.5% of price

    # ORB — first 15 min of NY session (3 x 5-min candles)
    orb_candles: int = 3

    # Risk management
    risk_reward_ratio: float = 2.0  # 1:2 RR
    trailing_stop_pct: float = 0.15  # optional trailing stop

    @property
    def all_symbols(self) -> List[str]:
        return self.forex_pairs + self.stocks
