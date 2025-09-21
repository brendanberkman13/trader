"""Playground for testing trading sessions and strategies."""

import asyncio
from datetime import datetime, timedelta
from loguru import logger

from src.trading.session import TradingSession
from src.strategies.ratioStrategy import RatioStrategy
from src.data.sources.backtest import BacktestDataSource


async def main():
    """Main playground function - backtesting."""

    # Set log level to INFO to hide DEBUG spam but keep final results
    logger.remove()
    logger.add(lambda msg: print(msg, end=''), level="INFO")  # Hide DEBUG, show INFO+

    # Set backtest time period based on COMP/SUSHI data availability
    end_time = datetime.now()
    # Both COMP and SUSHI data start 2025-03-25, use that as start date for maximum data
    start_time = datetime(2025, 3, 26)  # Start when we have all 4 symbols: UNI/SUSHI and AAVE/COMP

    # Create backtest data source with time bounds for progress tracking
    datasource = BacktestDataSource("data/trading.db", start_time=start_time, end_time=end_time)

    logger.info(f"Backtesting from {start_time} to {end_time}")
    logger.info(f"Backtest period: {(end_time - start_time).days} days")

    # Create a trading session with backtest executor
    session = TradingSession(
        datasource=datasource,
        capital=10000,
        executor_type='backtest',
        quiet_mode=True  # Suppress verbose logging, show progress bar instead
    )

    # Add strategies (session creates them with the datasource)

    # Strategy 1: DEX protocols pairs trade
    session.add_strategy(
        RatioStrategy,
        name="UNI_SUSHI_DEX",
        symbol_a="UNI/USDT",  # Numerator
        symbol_b="SUSHI/USDT",  # Denominator
        lookback_periods=240,  # 10 days of 5min data (enough for mean calculation)
        entry_threshold=2.0,   # Conservative entry
        exit_threshold=0.2,    # Quick exit when normalized
        allocation=0.5         # 50% of capital
    )

    # Strategy 2: DeFi lending protocols pairs trade
    session.add_strategy(
        RatioStrategy,
        name="AAVE_COMP_Lending",
        symbol_a="AAVE/USDT",  # Numerator (typically larger market cap)
        symbol_b="COMP/USDT",  # Denominator
        lookback_periods=240,  # Same lookback for consistency
        entry_threshold=1.8,   # Slightly more aggressive (lending is more volatile)
        exit_threshold=0.3,    # Slightly wider exit band
        allocation=0.5         # 50% of capital
    )

    # Run backtest
    await session.run(
        start_time=start_time,
        end_time=end_time,
        interval_seconds=300  # 5 minute intervals (more realistic for ratio trading)
    )


if __name__ == "__main__":
    asyncio.run(main())