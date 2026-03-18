"""Configuration for the 5-min scalp trading bot."""

from dataclasses import dataclass, field
from typing import List


@dataclass
class TradingConfig:
    # Paper trading
    initial_balance: float = 200.0
    risk_per_trade_pct: float = 5.0  # 5% risk per trade (aggressive)
    max_open_trades: int = 5

    # Instruments
    forex_pairs: List[str] = field(default_factory=lambda: [
        # Majors
        "EURUSD=X", "GBPUSD=X", "USDJPY=X", "USDCHF=X",
        "AUDUSD=X", "USDCAD=X", "NZDUSD=X",
        # Crosses
        "EURGBP=X", "EURJPY=X", "GBPJPY=X", "AUDJPY=X",
        "EURAUD=X", "EURCHF=X", "GBPCHF=X", "CADJPY=X",
        "NZDJPY=X", "GBPAUD=X", "AUDCAD=X", "AUDNZD=X",
        "EURNZD=X", "EURCAD=X", "GBPCAD=X", "GBPNZD=X",
        "CHFJPY=X", "CADCHF=X", "NZDCAD=X", "NZDCHF=X",
    ])
    stocks: List[str] = field(default_factory=list)

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
    risk_reward_ratio: float = 3.0  # 1:3 RR
    trailing_stop_pct: float = 0.15  # optional trailing stop

    @property
    def all_symbols(self) -> List[str]:
        return self.forex_pairs + self.stocks
