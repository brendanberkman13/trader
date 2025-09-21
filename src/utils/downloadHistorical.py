"""Download historical data from exchanges to backfill database."""

import ccxt
from datetime import datetime, timedelta
from loguru import logger
import time
from typing import List, Optional
import sys

from src.data.clients.Binance.binanceClient import BinanceClient
from src.data.storage.database import Database

# Setup logging
logger.remove()
logger.add(
    sys.stdout,
    colorize=True,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>"
)


class HistoricalDataDownloader:
    """Download historical OHLCV data from exchanges."""
    
    def __init__(self, exchange_name: str = "binanceus", db_path: str = "data/trading.db"):
        self.exchange = getattr(ccxt, exchange_name)({
            'enableRateLimit': True,
            'options': {'defaultType': 'spot'}
        })
        self.db = Database(db_path)
        
    def download_ohlcv(
        self,
        symbol: str,
        timeframe: str = '1h',
        days_back: int = 30,
        save_to_db: bool = True
    ) -> List:
        """Download historical OHLCV data."""
        
        logger.info(f"Downloading {days_back} days of {timeframe} data for {symbol}")
        
        # Calculate start timestamp
        since = self.exchange.parse8601(
            (datetime.now() - timedelta(days=days_back)).isoformat()
        )
        
        all_candles = []
        
        while since < self.exchange.milliseconds():
            try:
                # Fetch batch of candles
                candles = self.exchange.fetch_ohlcv(
                    symbol,
                    timeframe,
                    since,
                    limit=500  # Most exchanges limit to 500-1000
                )
                
                if not candles:
                    break
                
                all_candles.extend(candles)
                
                # Update since to last candle timestamp
                since = candles[-1][0] + 1
                
                logger.debug(f"Fetched {len(candles)} candles, total: {len(all_candles)}")
                
                # Rate limiting
                time.sleep(self.exchange.rateLimit / 1000)
                
            except Exception as e:
                logger.error(f"Error downloading data: {e}")
                break
        
        logger.success(f"Downloaded {len(all_candles)} total candles for {symbol}")
        
        if save_to_db and all_candles:
            self.save_candles_to_db(symbol, timeframe, all_candles)
        
        return all_candles
    
    def save_candles_to_db(self, symbol: str, timeframe: str, candles: List):
        """Save OHLCV candles to database."""
        
        # Convert to price records for the prices table
        # We'll save the close price as the "last" price
        saved_count = 0
        
        with self.db.get_connection() as conn:
            for candle in candles:
                timestamp = datetime.fromtimestamp(candle[0] / 1000)
                
                # Save to prices table (for strategy to use)
                try:
                    conn.execute("""
                        INSERT OR REPLACE INTO prices 
                        (symbol, timestamp, bid, ask, last, volume_24h)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        symbol,
                        timestamp,
                        candle[4] * 0.999,  # Simulate bid as slightly below close
                        candle[4] * 1.001,  # Simulate ask as slightly above close
                        candle[4],  # Close price as last
                        candle[5]   # Volume
                    ))
                    saved_count += 1
                except Exception as e:
                    logger.debug(f"Skipped duplicate: {e}")
                    
                # Also save to candles table
                try:
                    conn.execute("""
                        INSERT OR REPLACE INTO candles 
                        (symbol, timeframe, timestamp, open, high, low, close, volume)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        symbol,
                        timeframe,
                        timestamp,
                        candle[1],  # Open
                        candle[2],  # High
                        candle[3],  # Low
                        candle[4],  # Close
                        candle[5]   # Volume
                    ))
                except Exception as e:
                    logger.debug(f"Skipped candle: {e}")
        
        logger.success(f"Saved {saved_count} price records to database")
    
    def download_multiple_symbols(
        self,
        symbols: List[str],
        timeframe: str = '30m',
        days_back: int = 30
    ):
        """Download data for multiple symbols."""
        
        for symbol in symbols:
            self.download_ohlcv(symbol, timeframe, days_back)
            time.sleep(1)  # Be nice to the exchange
    
    def get_data_coverage(self) -> dict:
        """Check how much data we have for each symbol."""
        
        with self.db.get_connection() as conn:
            result = conn.execute("""
                SELECT 
                    symbol,
                    COUNT(*) as count,
                    MIN(timestamp) as earliest,
                    MAX(timestamp) as latest
                FROM prices
                GROUP BY symbol
            """).fetchall()
            
            coverage = {}
            for row in result:
                coverage[row['symbol']] = {
                    'count': row['count'],
                    'earliest': row['earliest'],
                    'latest': row['latest']
                }
            
            return coverage


def main():
    """Download historical data for backtesting."""
    
    logger.info("=" * 60)
    logger.info("HISTORICAL DATA DOWNLOADER")
    logger.info("=" * 60)
    
    downloader = HistoricalDataDownloader()
    
    # Check current data coverage
    logger.info("\nCurrent data coverage:")
    coverage = downloader.get_data_coverage()
    
    if not coverage:
        logger.warning("No existing data found")
    else:
        for symbol, info in coverage.items():
            logger.info(f"  {symbol}: {info['count']} records "
                       f"({info['earliest']} to {info['latest']})")
    
    # Download data - USER CONFIGURABLE SECTION
    logger.info("\nDownloading historical data...")
    
    # CONFIGURATION OPTIONS:
    # For 1 year of data with good granularity:
    
    # Option 1: 6 months of 5-minute data for robust testing
    timeframe = '5m'
    days_back = 180
    
    # Option 2: 6 months of 30-minute data (8,640 data points)
    # timeframe = '30m'
    # days_back = 180
    
    # Option 3: 3 months of 15-minute data (8,640 data points)
    # timeframe = '15m'
    # days_back = 90
    
    # Option 4: 1 month of 5-minute data (8,640 data points)
    # timeframe = '5m'
    # days_back = 30
    
    # PAIRS TRADING FOCUSED SYMBOLS
    symbols_to_download = [
        # Core pairs
        'BTC/USDT', 'ETH/USDT',

        # DeFi competitors (EXCELLENT for pairs trading)
        'UNI/USDT', 'SUSHI/USDT',  # DEX protocols - direct competitors
        'AAVE/USDT', 'COMP/USDT',  # Lending protocols - similar use cases

        # L1/L2 competitors
        'MATIC/USDT',  # L2 scaling solution
        'SOL/USDT', 'AVAX/USDT',   # Alt L1s - competitive ecosystems

        # Oracle tokens
        'LINK/USDT', 'BAND/USDT',  # Oracle services

        # Additional L1s
        'ADA/USDT', 'DOT/USDT',    # Alternative smart contract platforms
    ]

    # Remove duplicates while preserving order
    symbols_to_download = list(dict.fromkeys(symbols_to_download))
    
    logger.info(f"Configuration: {days_back} days of {timeframe} candles")
    expected_candles = {
        '5m': days_back * 24 * 12,
        '15m': days_back * 24 * 4,
        '30m': days_back * 24 * 2,
        '1h': days_back * 24,
        '4h': days_back * 6,
        '1d': days_back
    }
    
    if timeframe in expected_candles:
        logger.info(f"Expected ~{expected_candles[timeframe]:,} candles per symbol")
    
    for symbol in symbols_to_download:
        logger.info(f"\nDownloading {symbol}...")
        logger.info(f"This may take a few minutes for large datasets...")
        
        downloader.download_ohlcv(
            symbol=symbol,
            timeframe=timeframe,
            days_back=days_back,
            save_to_db=True
        )
        
        # Longer delay for rate limiting with large downloads
        time.sleep(3)
    
    # Optional: Download additional altcoins for more trading opportunities
    # Uncomment if you want more symbols:
    # additional_symbols = ['SOL/USDT', 'AVAX/USDT', 'LINK/USDT', 'UNI/USDT']
    # logger.info("\nDownloading additional altcoins...")
    # for symbol in additional_symbols:
    #     logger.info(f"Downloading {symbol}...")
    #     downloader.download_ohlcv(symbol, timeframe, days_back, save_to_db=True)
    #     time.sleep(3)
    
    # Check final coverage
    logger.info("\n" + "=" * 60)
    logger.info("FINAL DATA COVERAGE:")
    final_coverage = downloader.get_data_coverage()
    
    total_records = 0
    for symbol, info in final_coverage.items():
        days = 0
        if info['earliest'] and info['latest']:
            earliest = datetime.fromisoformat(info['earliest'])
            latest = datetime.fromisoformat(info['latest'])
            days = (latest - earliest).days
        
        total_records += info['count']
        logger.success(f"  {symbol}: {info['count']:,} records covering {days} days")
    
    logger.info(f"\nTotal records in database: {total_records:,}")
    
    # Recommendations based on data
    if total_records > 10000:
        logger.success("✅ EXCELLENT: Plenty of data for reliable backtesting!")
    elif total_records > 5000:
        logger.success("✅ GOOD: Sufficient data for meaningful backtesting")
    elif total_records > 1000:
        logger.info("✅ OK: Enough data for basic backtesting")
    else:
        logger.warning("⚠️  LIMITED: Results may not be statistically significant")
    
    logger.info("\nYou can now run: python run_backtest.py optimize")


if __name__ == "__main__":
    main()