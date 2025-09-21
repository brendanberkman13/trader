"""Base exchange client interface."""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple, Union
from datetime import datetime
from dataclasses import dataclass
import polars as pl


@dataclass
class Ticker:
    """Current market price data."""
    symbol: str
    timestamp: datetime
    bid: float
    ask: float
    last: float
    volume_24h: float


@dataclass
class Candle:
    """OHLCV candle data."""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class OrderBook:
    """Order book snapshot."""
    symbol: str
    timestamp: datetime
    bids: List[Tuple[Union[float, int], Union[float, int]]]  # More flexible types
    asks: List[Tuple[Union[float, int], Union[float, int]]]


class BaseExchangeClient(ABC):
    """Abstract base class all exchange clients must implement."""
    
    def __init__(self, api_key: Optional[str] = None, secret_key: Optional[str] = None):
        self.api_key = api_key
        self.secret_key = secret_key
        self.name = self.__class__.__name__.replace("Client", "").lower()
    
    @abstractmethod
    def get_ticker(self, symbol: str) -> Ticker:
        """Get current ticker for a symbol."""
        pass
    
    @abstractmethod
    def get_candles(
        self, 
        symbol: str, 
        timeframe: str,
        limit: int = 100
    ) -> List[Candle]:
        """Get historical OHLCV candles."""
        pass
    
    @abstractmethod
    def get_orderbook(self, symbol: str, depth: int = 20) -> OrderBook:
        """Get current order book."""
        pass
    
    @abstractmethod
    def get_balance(self) -> Dict[str, float]:
        """Get account balances. Returns {asset: amount}."""
        pass
    
    @abstractmethod
    def place_order(
        self,
        symbol: str,
        side: str,  # "buy" or "sell"
        amount: float,
        price: Optional[float] = None,  # None = market order
    ) -> dict:
        """Place an order. Returns order info."""
        pass
    
    @abstractmethod
    def cancel_order(self, order_id: str, symbol: str) -> bool:
        """Cancel an order. Returns success."""
        pass