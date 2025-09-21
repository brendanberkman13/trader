"""Price collector for continuous ticker data collection."""

import asyncio
from typing import List
from datetime import datetime
from loguru import logger

from .baseCollector import BaseCollector
from ..clients.Binance.binanceClient import BinanceClient
from ..storage.database import Database


class PriceCollector(BaseCollector):
    """Collects ticker prices continuously."""
    
    def __init__(
        self, 
        symbols: List[str], 
        interval_seconds: int = 30,
        db_path: str = "data/trading.db"
    ):
        super().__init__(symbols, interval_seconds)
        self.client = BinanceClient()
        self.db = Database(db_path)
        self.stats = {
            'collections': 0,
            'successes': 0,
            'failures': 0,
            'start_time': None
        }
    
    async def collect_once(self):
        """Collect current prices for all symbols."""
        self.stats['collections'] += 1
        
        for symbol in self.symbols:
            try:
                # Fetch ticker
                ticker = self.client.get_ticker(symbol)
                
                # Save to database
                success = self.db.save_ticker(ticker)
                
                if success:
                    self.stats['successes'] += 1
                    logger.debug(f"✓ {symbol}: ${ticker.last:,.2f} (spread: ${ticker.ask - ticker.bid:.2f})")
                else:
                    self.stats['failures'] += 1
                    
                # Small delay between symbols to be nice to API
                await asyncio.sleep(0.2)
                
            except Exception as e:
                self.stats['failures'] += 1
                logger.error(f"Failed to collect {symbol}: {e}")
        
        # Log summary every 10 collections
        if self.stats['collections'] % 10 == 0:
            self.log_stats()
    
    def log_stats(self):
        """Log collection statistics."""
        if self.stats['start_time']:
            runtime = (datetime.now() - self.stats['start_time']).total_seconds() / 60
            logger.info(
                f"📊 Stats: {self.stats['collections']} collections, "
                f"{self.stats['successes']} saved, "
                f"{self.stats['failures']} failed, "
                f"Runtime: {runtime:.1f} min"
            )
    
    async def start(self):
        """Start collection with stats tracking."""
        self.stats['start_time'] = datetime.now()
        logger.success(f"Starting price collection for: {', '.join(self.symbols)}")
        await super().start()


class CandleCollector(BaseCollector):
    """Collects historical candles periodically."""
    
    def __init__(
        self,
        symbols: List[str],
        timeframes: List[str] = ["1h", "4h"],
        interval_seconds: int = 3600,  # Every hour
        db_path: str = "data/trading.db"
    ):
        super().__init__(symbols, interval_seconds)
        self.client = BinanceClient()
        self.db = Database(db_path)
        self.timeframes = timeframes
    
    async def collect_once(self):
        """Collect recent candles for all symbols and timeframes."""
        for symbol in self.symbols:
            for timeframe in self.timeframes:
                try:
                    # Get recent candles
                    candles = self.client.get_candles(symbol, timeframe, limit=100)
                    
                    # Save to database
                    saved = self.db.save_candles(symbol, timeframe, candles)
                    
                    logger.debug(f"✓ {symbol} {timeframe}: Saved {saved} candles")
                    
                    await asyncio.sleep(0.5)  # Rate limiting
                    
                except Exception as e:
                    logger.error(f"Failed to collect candles for {symbol} {timeframe}: {e}")


class OrderBookCollector(BaseCollector):
    """Collects order book snapshots."""
    
    def __init__(
        self,
        symbols: List[str],
        interval_seconds: int = 60,
        depth: int = 20,
        db_path: str = "data/trading.db"
    ):
        super().__init__(symbols, interval_seconds)
        self.client = BinanceClient()
        self.db = Database(db_path)
        self.depth = depth
    
    async def collect_once(self):
        """Collect orderbook snapshots for all symbols."""
        for symbol in self.symbols:
            try:
                # Get orderbook
                orderbook = self.client.get_orderbook(symbol, self.depth)
                
                # Save to database
                success = self.db.save_orderbook(orderbook, symbol)
                
                if success and orderbook.bids and orderbook.asks:
                    spread = orderbook.asks[0][0] - orderbook.bids[0][0]
                    spread_pct = (spread / orderbook.bids[0][0]) * 100
                    logger.debug(f"✓ {symbol} orderbook: Spread {spread_pct:.3f}%")
                
                await asyncio.sleep(0.3)
                
            except Exception as e:
                logger.error(f"Failed to collect orderbook for {symbol}: {e}")


# Convenience function to run multiple collectors
async def run_collectors(
    symbols: List[str],
    collect_prices: bool = True,
    collect_candles: bool = False,
    collect_orderbooks: bool = False,
    price_interval: int = 30,
    candle_interval: int = 3600,
    orderbook_interval: int = 60
):
    """Run multiple collectors concurrently."""
    tasks = []
    
    if collect_prices:
        price_collector = PriceCollector(symbols, price_interval)
        tasks.append(asyncio.create_task(price_collector.start()))
    
    if collect_candles:
        candle_collector = CandleCollector(symbols, ["1h", "4h"], candle_interval)
        tasks.append(asyncio.create_task(candle_collector.start()))
    
    if collect_orderbooks:
        orderbook_collector = OrderBookCollector(symbols, orderbook_interval)
        tasks.append(asyncio.create_task(orderbook_collector.start()))
    
    if not tasks:
        logger.warning("No collectors enabled!")
        return
    
    logger.success(f"Running {len(tasks)} collectors. Press Ctrl+C to stop.")
    
    try:
        await asyncio.gather(*tasks)
    except KeyboardInterrupt:
        logger.info("Shutting down collectors...")
        for task in tasks:
            task.cancel()


if __name__ == "__main__":
    # Test the price collector
    async def test():
        # Top coins to collect
        symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "MATIC/USDT"]
        
        # Run just the price collector
        collector = PriceCollector(symbols, interval_seconds=10)  # Every 10 seconds for testing
        
        try:
            await collector.start()
        except KeyboardInterrupt:
            await collector.stop()
            collector.log_stats()
    
    # Run the test
    asyncio.run(test())