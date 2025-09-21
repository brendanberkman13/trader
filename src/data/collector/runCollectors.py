"""Run the data collector continuously."""

import asyncio
from loguru import logger
import sys

# Add better logging format
logger.remove()
logger.add(
    sys.stdout,
    colorize=True,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>"
)

from src.data.collector.priceCollector import PriceCollector, run_collectors


async def main():
    """Run data collection."""
    
    # Configuration
    SYMBOLS = [
        "BTC/USDT",
        "ETH/USDT", 
        "SOL/USDT",
        "AVAX/USDT",
        "MATIC/USDT",
        "LINK/USDT",
        "UNI/USDT",
        "AAVE/USDT"
    ]
    
    logger.info("=" * 60)
    logger.info("CRYPTO DATA COLLECTOR")
    logger.info("=" * 60)
    logger.info(f"Symbols: {', '.join(SYMBOLS)}")
    logger.info("Collection interval: 30 seconds")
    logger.info("Press Ctrl+C to stop")
    logger.info("=" * 60)
    
    # Method 1: Just price collection (recommended to start)
    collector = PriceCollector(
        symbols=SYMBOLS,
        interval_seconds=30  # Collect every 30 seconds
    )
    
    try:
        await collector.start()
    except KeyboardInterrupt:
        logger.info("\nShutting down...")
        await collector.stop()
        collector.log_stats()
        logger.success("Data collection stopped. Data saved to: data/trading.db")
    
    # Method 2: Run multiple collectors (uncomment to use)
    # await run_collectors(
    #     symbols=SYMBOLS,
    #     collect_prices=True,
    #     collect_candles=True,
    #     collect_orderbooks=False,  # This uses more API calls
    #     price_interval=30,
    #     candle_interval=3600,  # Every hour
    #     orderbook_interval=60
    # )


if __name__ == "__main__":
    asyncio.run(main())