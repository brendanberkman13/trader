"""Abstract DataSource interface for strategy data access."""

from abc import ABC, abstractmethod
from typing import Optional, List, Tuple
from datetime import datetime
from dataclasses import dataclass


@dataclass
class PriceData:
    """Price data point."""
    symbol: str
    price: float
    timestamp: datetime
    bid: Optional[float] = None
    ask: Optional[float] = None
    volume: Optional[float] = None


@dataclass
class CandleData:
    """OHLCV candle data."""
    symbol: str
    timeframe: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class OrderBookLevel:
    """Single order book level."""
    price: float
    quantity: float


@dataclass
class OrderBookData:
    """Order book snapshot."""
    symbol: str
    timestamp: datetime
    bids: List[OrderBookLevel]
    asks: List[OrderBookLevel]


class DataSource(ABC):
    """Abstract interface for strategy data access.

    This interface abstracts data access so strategies can work with
    both live data (from collectors/database) and historical data
    (for backtesting) using the same interface.
    """

    @abstractmethod
    async def get_current_price(self, symbol: str) -> Optional[PriceData]:
        """Get current/latest price for a symbol.

        Args:
            symbol: Trading symbol (e.g., 'BTC/USDT')

        Returns:
            Current price data or None if unavailable
        """
        pass

    @abstractmethod
    async def get_price_history(self, symbol: str, limit: int = 100) -> List[PriceData]:
        """Get historical price data for a symbol.

        Args:
            symbol: Trading symbol
            limit: Number of historical points to retrieve

        Returns:
            List of historical price data, ordered by timestamp (oldest first)
        """
        pass

    @abstractmethod
    async def get_candles(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 100
    ) -> List[CandleData]:
        """Get historical candle data.

        Args:
            symbol: Trading symbol
            timeframe: Timeframe (e.g., '1h', '4h', '1d')
            limit: Number of candles to retrieve

        Returns:
            List of candle data, ordered by timestamp (oldest first)
        """
        pass

    @abstractmethod
    async def get_orderbook(self, symbol: str, depth: int = 20) -> Optional[OrderBookData]:
        """Get current order book snapshot.

        Args:
            symbol: Trading symbol
            depth: Number of levels per side

        Returns:
            Order book data or None if unavailable
        """
        pass

    async def get_symbol_prices(self, symbols: List[str]) -> dict[str, Optional[PriceData]]:
        """Get current prices for multiple symbols.

        Args:
            symbols: List of trading symbols

        Returns:
            Dictionary mapping symbol to price data
        """
        result = {}
        for symbol in symbols:
            result[symbol] = await self.get_current_price(symbol)
        return result

    async def calculate_price_ratio(self, symbol1: str, symbol2: str) -> Optional[float]:
        """Calculate price ratio between two symbols.

        Args:
            symbol1: First symbol (numerator)
            symbol2: Second symbol (denominator)

        Returns:
            Ratio (symbol1_price / symbol2_price) or None if data unavailable
        """
        prices = await self.get_symbol_prices([symbol1, symbol2])

        price1_data = prices.get(symbol1)
        price2_data = prices.get(symbol2)

        if not price1_data or not price2_data:
            return None

        if price2_data.price <= 0:
            return None

        return price1_data.price / price2_data.price

    async def get_price_ratio_history(
        self,
        symbol1: str,
        symbol2: str,
        limit: int = 100
    ) -> List[Tuple[datetime, float]]:
        """Get historical price ratio data.

        Args:
            symbol1: First symbol (numerator)
            symbol2: Second symbol (denominator)
            limit: Number of historical points

        Returns:
            List of (timestamp, ratio) tuples, ordered by timestamp
        """
        # Get historical data for both symbols
        history1 = await self.get_price_history(symbol1, limit)
        history2 = await self.get_price_history(symbol2, limit)

        if not history1 or not history2:
            return []

        # Create dictionaries for fast lookup by timestamp
        prices1 = {data.timestamp: data.price for data in history1}
        prices2 = {data.timestamp: data.price for data in history2}

        # Find common timestamps and calculate ratios
        common_timestamps = set(prices1.keys()) & set(prices2.keys())

        ratios = []
        for timestamp in sorted(common_timestamps):
            price1 = prices1[timestamp]
            price2 = prices2[timestamp]

            if price2 > 0:  # Avoid division by zero
                ratio = price1 / price2
                ratios.append((timestamp, ratio))

        return ratios[-limit:]  # Return most recent 'limit' ratios