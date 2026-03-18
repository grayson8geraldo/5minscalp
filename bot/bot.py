"""Main bot engine — orchestrates data fetching, analysis, signal generation, and paper trading."""

import logging
import time as time_mod
from datetime import datetime, time, timedelta
from typing import Dict, List

import pytz

from bot.config import TradingConfig
from bot.data_fetcher import fetch_candles, get_latest_price
from bot.entry_models import TradeSignal, find_signals
from bot.paper_trader import PaperTrader
from bot.sessions import AMDContext, analyse_amd

logger = logging.getLogger(__name__)
UTC = pytz.utc
ET = pytz.timezone("US/Eastern")


def is_ny_session_active() -> bool:
    """Check if we're currently in NY session (9:30-16:00 ET)."""
    now_et = datetime.now(ET)
    start = time(9, 30)
    end = time(16, 0)
    return start <= now_et.time() <= end


def is_market_open() -> bool:
    """Check if it's a weekday and roughly market hours."""
    now_et = datetime.now(ET)
    # Mon=0 .. Fri=4
    if now_et.weekday() > 4:
        return False
    return True


class TradingBot:
    def __init__(self, cfg: TradingConfig):
        self.cfg = cfg
        self.trader = PaperTrader(cfg)
        self.processed_signals: set = set()  # avoid duplicates

    def scan_all_symbols(self) -> List[TradeSignal]:
        """Scan all configured symbols for trade signals."""
        all_signals: List[TradeSignal] = []
        today = datetime.now(UTC)

        for symbol in self.cfg.all_symbols:
            logger.info("Scanning %s ...", symbol)
            df = fetch_candles(symbol, self.cfg.interval, days=5)
            if df is None or len(df) < 20:
                continue

            amd = analyse_amd(df, today, symbol, self.cfg)

            if not amd.asian_valid:
                logger.info("  %s: Asian range too wide (%.2f%%), skipping", symbol,
                           amd.asian.range_pct if amd.asian else 0)
                continue

            if not amd.expected_ny_direction:
                logger.info("  %s: No clear direction, skipping", symbol)
                continue

            if amd.is_stock:
                logger.info(
                    "  %s: [Stock] direction=%s (prev_day_bias=%s)",
                    symbol, amd.expected_ny_direction, amd.prev_day_bias,
                )
            else:
                logger.info(
                    "  %s: [Forex] AMD direction=%s (manipulation=%s)",
                    symbol, amd.expected_ny_direction, amd.london_manipulation,
                )

            signals = find_signals(df, amd, self.cfg)
            all_signals.extend(signals)

        return all_signals

    def execute_signals(self, signals: List[TradeSignal]):
        """Open paper trades for new signals."""
        for sig in signals:
            sig_key = f"{sig.symbol}_{sig.model}_{sig.timestamp}"
            if sig_key in self.processed_signals:
                continue
            self.processed_signals.add(sig_key)

            trade = self.trader.open_trade(
                symbol=sig.symbol,
                direction=sig.direction,
                entry_price=sig.entry_price,
                stop_loss=sig.stop_loss,
                take_profit=sig.take_profit,
                model=sig.model,
            )
            if trade:
                logger.info("Executed signal: %s", sig_key)

    def update_open_trades(self):
        """Fetch latest prices and check SL/TP for open trades."""
        open_trades = self.trader.account.open_trades
        if not open_trades:
            return

        symbols_needed = {t.symbol for t in open_trades}
        prices: Dict[str, float] = {}
        for sym in symbols_needed:
            p = get_latest_price(sym)
            if p:
                prices[sym] = p

        self.trader.update_trades(prices)

    def run_cycle(self):
        """Run one full scan-and-trade cycle."""
        logger.info("=" * 60)
        logger.info("Cycle start: %s", datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"))
        logger.info("Balance: $%.2f", self.trader.account.balance)

        # Update existing trades first
        self.update_open_trades()

        # Scan for new signals
        signals = self.scan_all_symbols()
        if signals:
            logger.info("Found %d signal(s)", len(signals))
            self.execute_signals(signals)
        else:
            logger.info("No signals found this cycle")

        # Print stats
        stats = self.trader.get_stats()
        logger.info(
            "Stats: Balance=$%.2f | PnL=$%.2f (%.1f%%) | Trades=%d | WR=%.1f%% | Open=%d",
            stats["balance"], stats["total_pnl"], stats["pnl_pct"],
            stats["total_trades"], stats["win_rate"], stats["open_trades"],
        )
        logger.info("=" * 60)

    def run(self, interval_minutes: int = 5):
        """Main loop — run continuously every N minutes."""
        logger.info("5-Min Scalp Bot started | Paper trading with $%.2f",
                    self.cfg.initial_balance)
        logger.info("Symbols: %s", ", ".join(self.cfg.all_symbols))
        logger.info("Scan interval: %d minutes", interval_minutes)

        while True:
            try:
                if is_market_open():
                    self.run_cycle()
                else:
                    logger.info("Market closed. Waiting...")
            except KeyboardInterrupt:
                logger.info("Bot stopped by user")
                break
            except Exception as e:
                logger.error("Error in cycle: %s", e, exc_info=True)

            time_mod.sleep(interval_minutes * 60)
