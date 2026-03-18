#!/usr/bin/env python3
"""5-Minute Scalp Trading Bot — Paper Trading with Real Market Data.

Strategy: AMD (Accumulation-Manipulation-Distribution)
Entry models: Support/Resistance, Supply/Demand, Open Range Breakout
Final trigger: Engulfing candlestick pattern
"""

import argparse
import logging
import sys

from tabulate import tabulate

from bot.bot import TradingBot
from bot.config import TradingConfig
from bot.paper_trader import PaperAccount


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def cmd_run(args):
    """Start the trading bot."""
    cfg = TradingConfig(initial_balance=args.balance)
    if args.symbols:
        # Override default symbols
        forex = [s for s in args.symbols if "=" in s]
        stocks = [s for s in args.symbols if "=" not in s]
        cfg.forex_pairs = forex
        cfg.stocks = stocks

    bot = TradingBot(cfg)
    bot.run(interval_minutes=args.interval)


def cmd_scan(args):
    """Run a single scan cycle (no loop)."""
    cfg = TradingConfig(initial_balance=args.balance)
    bot = TradingBot(cfg)
    bot.run_cycle()


def cmd_stats(args):
    """Show paper trading statistics."""
    account = PaperAccount.load()
    stats = {
        "Balance": f"${account.balance:.2f}",
        "Initial": f"${account.initial_balance:.2f}",
        "Total PnL": f"${account.total_pnl:.2f}",
        "PnL %": f"{account.total_pnl / account.initial_balance * 100:.1f}%",
        "Win Rate": f"{account.win_rate:.1f}%",
        "Total Trades": len(account.closed_trades),
        "Open Trades": len(account.open_trades),
    }
    print("\n=== Paper Trading Stats ===")
    for k, v in stats.items():
        print(f"  {k:>15}: {v}")

    if account.open_trades:
        print("\n--- Open Trades ---")
        rows = []
        for t in account.open_trades:
            rows.append([
                t.id, t.symbol, t.direction.upper(), t.model,
                f"{t.entry_price:.5f}", f"{t.stop_loss:.5f}",
                f"{t.take_profit:.5f}", f"${t.risk_amount:.2f}",
            ])
        print(tabulate(rows,
              headers=["#", "Symbol", "Dir", "Model", "Entry", "SL", "TP", "Risk"],
              tablefmt="simple"))

    if account.closed_trades:
        print("\n--- Recent Closed Trades (last 10) ---")
        rows = []
        for t in account.closed_trades[-10:]:
            rows.append([
                t.id, t.symbol, t.direction.upper(), t.model,
                t.status.upper(),
                f"{t.entry_price:.5f}", f"{t.exit_price:.5f}" if t.exit_price else "-",
                f"${t.pnl:.2f}" if t.pnl else "-",
            ])
        print(tabulate(rows,
              headers=["#", "Symbol", "Dir", "Model", "Result", "Entry", "Exit", "PnL"],
              tablefmt="simple"))
    print()


def cmd_reset(args):
    """Reset paper trading account."""
    account = PaperAccount(balance=args.balance, initial_balance=args.balance)
    account.save()
    print(f"Account reset. Balance: ${args.balance:.2f}")


def main():
    parser = argparse.ArgumentParser(
        description="5-Min Scalp Trading Bot — Paper Trading",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging")
    sub = parser.add_subparsers(dest="command")

    # run
    p_run = sub.add_parser("run", help="Start the bot (continuous loop)")
    p_run.add_argument("--balance", type=float, default=200.0, help="Starting balance")
    p_run.add_argument("--interval", type=int, default=5, help="Scan interval in minutes")
    p_run.add_argument("--symbols", nargs="+", help="Override symbols (e.g. AAPL EURUSD=X)")
    p_run.set_defaults(func=cmd_run)

    # scan
    p_scan = sub.add_parser("scan", help="Run a single scan cycle")
    p_scan.add_argument("--balance", type=float, default=200.0)
    p_scan.set_defaults(func=cmd_scan)

    # stats
    p_stats = sub.add_parser("stats", help="Show paper trading stats")
    p_stats.set_defaults(func=cmd_stats)

    # reset
    p_reset = sub.add_parser("reset", help="Reset paper account")
    p_reset.add_argument("--balance", type=float, default=200.0, help="Starting balance")
    p_reset.set_defaults(func=cmd_reset)

    args = parser.parse_args()
    setup_logging(args.verbose)

    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
