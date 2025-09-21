"""Live data source implementation using database."""

from typing import Optional, List
from datetime import datetime
from loguru import logger

from .base import DataSource, PriceData, CandleData, OrderBookData, OrderBookLevel
from ..storage.database import Database


class LiveDataSource(DataSource):
    """Live data source that queries the database for real-time data.

    This implementation gets the most recent data from the database,
    which is populated by the collectors running in the background.
    """

    def __init__(self, db_path: str = "data/trading.db"):
        """Initialize with database connection.

        Args:
            db_path: Path to the SQLite database
        """
        self.db = Database(db_path)

    async def get_current_price(self, symbol: str) -> Optional[PriceData]:
        """Get the most recent price from database.

        Args:
            symbol: Trading symbol (e.g., 'BTC/USDT')

        Returns:
            Current price data or None if unavailable
        """
        try:
            with self.db.get_connection() as conn:
                query = """
                    SELECT symbol, last, timestamp, bid, ask
                    FROM prices
                    WHERE symbol = ?
                    ORDER BY timestamp DESC
                    LIMIT 1
                """

                result = conn.execute(query, (symbol,)).fetchone()

                if not result:
                    logger.debug(f"No price data found for {symbol}")
                    return None

                return PriceData(
                    symbol=result[0],
                    price=float(result[1]),
                    timestamp=datetime.fromisoformat(result[2]),
                    bid=float(result[3]) if result[3] else None,
                    ask=float(result[4]) if result[4] else None,
                    volume=None  # Volume not in current schema
                )

        except Exception as e:
            logger.error(f"Error fetching current price for {symbol}: {e}")
            return None

    async def get_price_history(self, symbol: str, limit: int = 100) -> List[PriceData]:
        """Get historical price data from database.

        Args:
            symbol: Trading symbol
            limit: Number of historical points to retrieve

        Returns:
            List of historical price data, ordered by timestamp (oldest first)
        """
        try:
            with self.db.get_connection() as conn:
                query = """
                    SELECT symbol, last, timestamp, bid, ask
                    FROM prices
                    WHERE symbol = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                """

                results = conn.execute(query, (symbol, limit)).fetchall()

                if not results:
                    logger.debug(f"No price history found for {symbol}")
                    return []

                # Reverse to get oldest first
                price_data = []
                for row in reversed(results):
                    price_data.append(PriceData(
                        symbol=row[0],
                        price=float(row[1]),
                        timestamp=datetime.fromisoformat(row[2]),
                        bid=float(row[3]) if row[3] else None,
                        ask=float(row[4]) if row[4] else None,
                        volume=None  # Volume not in current schema
                    ))

                return price_data

        except Exception as e:
            logger.error(f"Error fetching price history for {symbol}: {e}")
            return []

    async def get_candles(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 100
    ) -> List[CandleData]:
        """Get historical candle data from database.

        Args:
            symbol: Trading symbol
            timeframe: Timeframe (e.g., '1h', '4h', '1d')
            limit: Number of candles to retrieve

        Returns:
            List of candle data, ordered by timestamp (oldest first)
        """
        try:
            with self.db.get_connection() as conn:
                query = """
                    SELECT symbol, timeframe, timestamp, open, high, low, close, volume
                    FROM candles
                    WHERE symbol = ? AND timeframe = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                """

                results = conn.execute(query, (symbol, timeframe, limit)).fetchall()

                if not results:
                    logger.debug(f"No candle data found for {symbol} {timeframe}")
                    return []

                # Reverse to get oldest first
                candle_data = []
                for row in reversed(results):
                    candle_data.append(CandleData(
                        symbol=row[0],
                        timeframe=row[1],
                        timestamp=datetime.fromisoformat(row[2]),
                        open=float(row[3]),
                        high=float(row[4]),
                        low=float(row[5]),
                        close=float(row[6]),
                        volume=float(row[7])
                    ))

                return candle_data

        except Exception as e:
            logger.error(f"Error fetching candles for {symbol} {timeframe}: {e}")
            return []

    async def get_orderbook(self, symbol: str, depth: int = 20) -> Optional[OrderBookData]:
        """Get current order book snapshot from database.

        Args:
            symbol: Trading symbol
            depth: Number of levels per side

        Returns:
            Order book data or None if unavailable
        """
        try:
            with self.db.get_connection() as conn:
                # Get the most recent orderbook entry
                query = """
                    SELECT symbol, timestamp, bids_json, asks_json
                    FROM orderbooks
                    WHERE symbol = ?
                    ORDER BY timestamp DESC
                    LIMIT 1
                """

                result = conn.execute(query, (symbol,)).fetchone()

                if not result:
                    logger.debug(f"No orderbook data found for {symbol}")
                    return None

                import json

                # Parse JSON data
                bids_data = json.loads(result[2])
                asks_data = json.loads(result[3])

                # Convert to OrderBookLevel objects and limit depth
                bids = [
                    OrderBookLevel(price=float(level[0]), quantity=float(level[1]))
                    for level in bids_data[:depth]
                ]
                asks = [
                    OrderBookLevel(price=float(level[0]), quantity=float(level[1]))
                    for level in asks_data[:depth]
                ]

                return OrderBookData(
                    symbol=result[0],
                    timestamp=datetime.fromisoformat(result[1]),
                    bids=bids,
                    asks=asks
                )

        except Exception as e:
            logger.error(f"Error fetching orderbook for {symbol}: {e}")
            return None

    async def is_data_fresh(self, symbol: str, max_age_seconds: int = 300) -> bool:
        """Check if data for a symbol is fresh (recent).

        Args:
            symbol: Trading symbol
            max_age_seconds: Maximum age in seconds to consider fresh

        Returns:
            True if data is fresh, False otherwise
        """
        price_data = await self.get_current_price(symbol)

        if not price_data:
            return False

        age_seconds = (datetime.now() - price_data.timestamp).total_seconds()
        return age_seconds <= max_age_seconds

    async def get_data_age(self, symbol: str) -> Optional[float]:
        """Get the age of the most recent data in seconds.

        Args:
            symbol: Trading symbol

        Returns:
            Age in seconds or None if no data
        """
        price_data = await self.get_current_price(symbol)

        if not price_data:
            return None

        return (datetime.now() - price_data.timestamp).total_seconds()

    def get_database(self) -> Database:
        """Get the underlying database instance.

        Returns:
            Database instance for advanced queries
        """
        return self.db