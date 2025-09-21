"""Backtest data source implementation using simulated time."""

from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from loguru import logger

from .base import DataSource, PriceData, CandleData, OrderBookData, OrderBookLevel
from ..storage.database import Database


class BacktestDataSource(DataSource):
    """Backtest data source that provides historical data as if it were live.

    This implementation simulates live data by returning historical data
    based on a current_time that advances through the backtest period.
    """

    def __init__(
        self,
        db_path: str = "data/trading.db",
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ):
        """Initialize backtest data source.

        Args:
            db_path: Path to the SQLite database
            start_time: Start time for backtest (defaults to earliest data)
            end_time: End time for backtest (defaults to latest data)
        """
        self.db = Database(db_path)
        self.current_time = start_time
        self.start_time = start_time
        self.end_time = end_time

        # Cache for performance
        self._price_cache: Dict[str, List[PriceData]] = {}
        self._cache_loaded = False

    def set_current_time(self, current_time: datetime):
        """Set the current simulated time for backtesting.

        Args:
            current_time: The simulated current time
        """
        self.current_time = current_time

    def advance_time(self, minutes: int = 1):
        """Advance the current time by specified minutes.

        Args:
            minutes: Number of minutes to advance
        """
        if self.current_time:
            self.current_time += timedelta(minutes=minutes)

    async def _load_data_cache(self):
        """Load all historical data into cache for faster backtesting."""
        if self._cache_loaded:
            return

        logger.info("Loading historical data for backtesting...")

        try:
            with self.db.get_connection() as conn:
                # Load all price data for the backtest period
                query = """
                    SELECT DISTINCT symbol FROM prices
                """
                symbols = [row[0] for row in conn.execute(query).fetchall()]

                for symbol in symbols:
                    price_query = """
                        SELECT symbol, last, timestamp, bid, ask
                        FROM prices
                        WHERE symbol = ?
                    """

                    # Add time constraints if specified
                    params = [symbol]
                    if self.start_time:
                        price_query += " AND timestamp >= ?"
                        params.append(self.start_time.isoformat())
                    if self.end_time:
                        price_query += " AND timestamp <= ?"
                        params.append(self.end_time.isoformat())

                    price_query += " ORDER BY timestamp ASC"

                    results = conn.execute(price_query, params).fetchall()

                    price_data = []
                    for row in results:
                        price_data.append(PriceData(
                            symbol=row[0],
                            price=float(row[1]),
                            timestamp=datetime.fromisoformat(row[2]),
                            bid=float(row[3]) if row[3] else None,
                            ask=float(row[4]) if row[4] else None,
                            volume=None  # Volume not available in current schema
                        ))

                    self._price_cache[symbol] = price_data

            self._cache_loaded = True
            logger.success(f"Loaded data for {len(self._price_cache)} symbols")

        except Exception as e:
            logger.error(f"Error loading backtest data cache: {e}")
            raise

    async def get_current_price(self, symbol: str) -> Optional[PriceData]:
        """Get price at current simulated time.

        Args:
            symbol: Trading symbol

        Returns:
            Price data at current time or None if unavailable
        """
        if not self.current_time:
            logger.warning("No current_time set for backtest data source")
            return None

        await self._load_data_cache()

        if symbol not in self._price_cache:
            logger.debug(f"No cached data for {symbol}")
            return None

        # Find the most recent price at or before current_time
        symbol_data = self._price_cache[symbol]

        # Binary search for efficiency
        left, right = 0, len(symbol_data) - 1
        result_idx = -1

        while left <= right:
            mid = (left + right) // 2
            if symbol_data[mid].timestamp <= self.current_time:
                result_idx = mid
                left = mid + 1
            else:
                right = mid - 1

        if result_idx == -1:
            return None

        return symbol_data[result_idx]

    async def get_price_history(self, symbol: str, limit: int = 100) -> List[PriceData]:
        """Get historical price data up to current simulated time.

        Args:
            symbol: Trading symbol
            limit: Number of historical points to retrieve

        Returns:
            List of historical price data, ordered by timestamp (oldest first)
        """
        if not self.current_time:
            return []

        await self._load_data_cache()

        if symbol not in self._price_cache:
            return []

        # Get all data up to current_time
        symbol_data = self._price_cache[symbol]
        valid_data = [
            data for data in symbol_data
            if data.timestamp <= self.current_time
        ]

        # Return the most recent 'limit' data points
        return valid_data[-limit:] if valid_data else []

    async def get_candles(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 100
    ) -> List[CandleData]:
        """Get historical candle data up to current simulated time.

        Args:
            symbol: Trading symbol
            timeframe: Timeframe (e.g., '1h', '4h', '1d')
            limit: Number of candles to retrieve

        Returns:
            List of candle data, ordered by timestamp (oldest first)
        """
        if not self.current_time:
            return []

        try:
            with self.db.get_connection() as conn:
                query = """
                    SELECT symbol, timeframe, timestamp, open, high, low, close, volume
                    FROM candles
                    WHERE symbol = ? AND timeframe = ? AND timestamp <= ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                """

                results = conn.execute(
                    query,
                    (symbol, timeframe, self.current_time.isoformat(), limit)
                ).fetchall()

                if not results:
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
            logger.error(f"Error fetching backtest candles for {symbol}: {e}")
            return []

    async def get_orderbook(self, symbol: str, depth: int = 20) -> Optional[OrderBookData]:
        """Get order book at current simulated time.

        Note: This is a simplified implementation. In real backtesting,
        you might want more sophisticated orderbook reconstruction.

        Args:
            symbol: Trading symbol
            depth: Number of levels per side

        Returns:
            Simulated order book data or None if unavailable
        """
        # Get current price to simulate orderbook around
        current_price_data = await self.get_current_price(symbol)

        if not current_price_data:
            return None

        price = current_price_data.price

        # Simulate a simple orderbook around current price
        # This is a basic implementation - real orderbook reconstruction
        # would be more complex
        spread_pct = 0.001  # 0.1% spread

        bids = []
        asks = []

        for i in range(depth):
            # Bids below current price
            bid_price = price * (1 - spread_pct/2 - (i * 0.0001))
            bid_qty = 100.0 + (i * 10)  # Simulated quantity
            bids.append(OrderBookLevel(price=bid_price, quantity=bid_qty))

            # Asks above current price
            ask_price = price * (1 + spread_pct/2 + (i * 0.0001))
            ask_qty = 100.0 + (i * 10)  # Simulated quantity
            asks.append(OrderBookLevel(price=ask_price, quantity=ask_qty))

        return OrderBookData(
            symbol=symbol,
            timestamp=self.current_time or datetime.now(),
            bids=bids,
            asks=asks
        )

    async def get_available_symbols(self) -> List[str]:
        """Get list of symbols available for backtesting.

        Returns:
            List of available trading symbols
        """
        await self._load_data_cache()
        return list(self._price_cache.keys())

    async def get_data_range(self, symbol: Optional[str] = None) -> tuple[Optional[datetime], Optional[datetime]]:
        """Get the date range of available data.

        Args:
            symbol: Optional symbol to check (if None, checks all symbols)

        Returns:
            Tuple of (earliest_date, latest_date)
        """
        await self._load_data_cache()

        if symbol and symbol in self._price_cache:
            data = self._price_cache[symbol]
            if data:
                return data[0].timestamp, data[-1].timestamp
            return None, None

        # Check all symbols
        earliest = None
        latest = None

        for symbol_data in self._price_cache.values():
            if not symbol_data:
                continue

            first_time = symbol_data[0].timestamp
            last_time = symbol_data[-1].timestamp

            if earliest is None or first_time < earliest:
                earliest = first_time

            if latest is None or last_time > latest:
                latest = last_time

        return earliest, latest

    def reset(self):
        """Reset the backtest data source."""
        self.current_time = self.start_time
        # Keep cache loaded for efficiency

    def get_progress(self) -> Optional[float]:
        """Get backtest progress as percentage.

        Returns:
            Progress percentage (0-100) or None if times not set
        """
        if not self.current_time or not self.start_time or not self.end_time:
            return None

        total_duration = (self.end_time - self.start_time).total_seconds()
        current_duration = (self.current_time - self.start_time).total_seconds()

        if total_duration <= 0:
            return 100.0

        return min(100.0, (current_duration / total_duration) * 100.0)