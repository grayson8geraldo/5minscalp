"""Paper trading engine — virtual $200 balance, real market data."""

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

import pytz

from bot.config import TradingConfig

logger = logging.getLogger(__name__)

TRADES_FILE = "trades.json"
BALANCE_FILE = "paper_balance.json"


@dataclass
class PaperTrade:
    id: int
    symbol: str
    direction: str  # "long" or "short"
    entry_price: float
    stop_loss: float
    take_profit: float
    size: float  # position size in units
    risk_amount: float  # dollar risk
    model: str
    opened_at: str
    closed_at: Optional[str] = None
    exit_price: Optional[float] = None
    pnl: Optional[float] = None
    status: str = "open"  # "open", "win", "loss", "breakeven"


@dataclass
class PaperAccount:
    balance: float = 200.0
    initial_balance: float = 200.0
    trades: List[PaperTrade] = field(default_factory=list)
    next_id: int = 1

    def save(self):
        data = {
            "balance": self.balance,
            "initial_balance": self.initial_balance,
            "next_id": self.next_id,
            "trades": [asdict(t) for t in self.trades],
        }
        with open(BALANCE_FILE, "w") as f:
            json.dump(data, f, indent=2)

    @classmethod
    def load(cls) -> "PaperAccount":
        if not os.path.exists(BALANCE_FILE):
            return cls()
        try:
            with open(BALANCE_FILE) as f:
                data = json.load(f)
            acct = cls(
                balance=data["balance"],
                initial_balance=data["initial_balance"],
                next_id=data.get("next_id", 1),
            )
            for td in data.get("trades", []):
                acct.trades.append(PaperTrade(**td))
            return acct
        except Exception as e:
            logger.error("Failed to load account: %s", e)
            return cls()

    @property
    def open_trades(self) -> List[PaperTrade]:
        return [t for t in self.trades if t.status == "open"]

    @property
    def closed_trades(self) -> List[PaperTrade]:
        return [t for t in self.trades if t.status != "open"]

    @property
    def total_pnl(self) -> float:
        return sum(t.pnl for t in self.closed_trades if t.pnl is not None)

    @property
    def win_rate(self) -> float:
        closed = self.closed_trades
        if not closed:
            return 0.0
        wins = sum(1 for t in closed if t.status == "win")
        return wins / len(closed) * 100


class PaperTrader:
    def __init__(self, cfg: TradingConfig):
        self.cfg = cfg
        self.account = PaperAccount.load()
        if self.account.balance <= 0:
            self.account = PaperAccount(balance=cfg.initial_balance,
                                         initial_balance=cfg.initial_balance)

    def open_trade(
        self,
        symbol: str,
        direction: str,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        model: str,
    ) -> Optional[PaperTrade]:
        """Open a new paper trade with proper position sizing."""
        if len(self.account.open_trades) >= self.cfg.max_open_trades:
            logger.warning("Max open trades reached (%d)", self.cfg.max_open_trades)
            return None

        risk_amount = self.account.balance * (self.cfg.risk_per_trade_pct / 100)
        sl_distance = abs(entry_price - stop_loss)
        if sl_distance == 0:
            logger.warning("SL distance is 0, skipping")
            return None

        size = risk_amount / sl_distance

        trade = PaperTrade(
            id=self.account.next_id,
            symbol=symbol,
            direction=direction,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            size=size,
            risk_amount=risk_amount,
            model=model,
            opened_at=datetime.now(tz=pytz.utc).isoformat(),
        )

        self.account.next_id += 1
        self.account.trades.append(trade)
        self.account.save()

        logger.info(
            "OPENED trade #%d: %s %s @ %.5f | Size=%.4f | SL=%.5f TP=%.5f | Risk=$%.2f",
            trade.id, direction.upper(), symbol, entry_price,
            size, stop_loss, take_profit, risk_amount,
        )
        return trade

    def update_trades(self, prices: Dict[str, float]):
        """Check open trades against current prices and close if SL/TP hit."""
        for trade in self.account.open_trades:
            price = prices.get(trade.symbol)
            if price is None:
                continue

            hit_tp = False
            hit_sl = False

            if trade.direction == "long":
                hit_tp = price >= trade.take_profit
                hit_sl = price <= trade.stop_loss
            else:
                hit_tp = price <= trade.take_profit
                hit_sl = price >= trade.stop_loss

            if hit_tp:
                self._close_trade(trade, trade.take_profit, "win")
            elif hit_sl:
                self._close_trade(trade, trade.stop_loss, "loss")

    def _close_trade(self, trade: PaperTrade, exit_price: float, status: str):
        if trade.direction == "long":
            pnl = (exit_price - trade.entry_price) * trade.size
        else:
            pnl = (trade.entry_price - exit_price) * trade.size

        trade.exit_price = exit_price
        trade.pnl = round(pnl, 4)
        trade.status = status
        trade.closed_at = datetime.now(tz=pytz.utc).isoformat()

        self.account.balance += pnl
        self.account.save()

        logger.info(
            "CLOSED trade #%d [%s]: %s %s @ %.5f → %.5f | PnL=$%.2f | Balance=$%.2f",
            trade.id, status.upper(), trade.direction.upper(), trade.symbol,
            trade.entry_price, exit_price, pnl, self.account.balance,
        )

    def get_stats(self) -> dict:
        return {
            "balance": round(self.account.balance, 2),
            "initial_balance": self.account.initial_balance,
            "total_pnl": round(self.account.total_pnl, 2),
            "pnl_pct": round(self.account.total_pnl / self.account.initial_balance * 100, 2),
            "total_trades": len(self.account.closed_trades),
            "open_trades": len(self.account.open_trades),
            "win_rate": round(self.account.win_rate, 1),
            "wins": sum(1 for t in self.account.closed_trades if t.status == "win"),
            "losses": sum(1 for t in self.account.closed_trades if t.status == "loss"),
        }
