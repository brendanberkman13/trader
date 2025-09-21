"""Data models for trading system."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Literal
from enum import Enum


class OrderSide(Enum):
    """Order side enumeration."""
    BUY = "buy"
    SELL = "sell"


class OrderType(Enum):
    """Order type enumeration."""
    MARKET = "market"
    LIMIT = "limit"


class SignalType(Enum):
    """Trading signal type."""
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class Signal:
    """Trading signal from a strategy."""
    symbol: str
    signal: SignalType
    strength: float  # 0-1 confidence/strength
    price: float
    reason: str
    strategy_id: Optional[str] = None  # Will be set by TradingSession
    timestamp: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        """Validate signal strength is in valid range."""
        if not 0 <= self.strength <= 1:
            raise ValueError(f"Signal strength must be between 0 and 1, got {self.strength}")


@dataclass
class Order:
    """Order to be executed."""
    symbol: str
    side: OrderSide
    size: float  # Dollar amount
    order_type: OrderType = OrderType.MARKET
    strategy_id: Optional[str] = None
    limit_price: Optional[float] = None  # For limit orders
    timestamp: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        """Validate order parameters."""
        if self.size <= 0:
            raise ValueError(f"Order size must be positive, got {self.size}")

        if self.order_type == OrderType.LIMIT and self.limit_price is None:
            raise ValueError("Limit orders require a limit_price")

        # Convert string to enum if needed
        if isinstance(self.side, str):
            self.side = OrderSide(self.side)
        if isinstance(self.order_type, str):
            self.order_type = OrderType(self.order_type)


@dataclass
class Fill:
    """Executed order fill details."""
    order: Order
    executed_price: float
    executed_size: float  # Dollar amount actually filled
    fees: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)
    slippage: float = 0.0  # Price difference from expected

    def __post_init__(self):
        """Validate fill parameters."""
        if self.executed_price <= 0:
            raise ValueError(f"Executed price must be positive, got {self.executed_price}")

        if self.executed_size < 0:
            raise ValueError(f"Executed size cannot be negative, got {self.executed_size}")

        if self.fees < 0:
            raise ValueError(f"Fees cannot be negative, got {self.fees}")

        # Calculate slippage if we have a limit price
        if self.order.limit_price:
            if self.order.side == OrderSide.BUY:
                self.slippage = self.executed_price - self.order.limit_price
            else:  # SELL
                self.slippage = self.order.limit_price - self.executed_price

    @property
    def net_size(self) -> float:
        """Get size after fees."""
        return self.executed_size - self.fees

    @property
    def fill_rate(self) -> float:
        """Get percentage of order that was filled."""
        if self.order.size == 0:
            return 0.0
        return self.executed_size / self.order.size


@dataclass
class Position:
    """Track an open position."""
    symbol: str
    strategy_id: str
    side: Literal["long", "short"]
    entry_price: float
    size: float  # Dollar amount
    quantity: float  # Number of units (size / entry_price)
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    entry_time: datetime = field(default_factory=datetime.now)
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    fees_paid: float = 0.0

    def __post_init__(self):
        """Initialize quantity if not set."""
        if self.quantity == 0 and self.entry_price > 0:
            self.quantity = self.size / self.entry_price

        if self.current_price == 0:
            self.current_price = self.entry_price

        self.update_price(self.current_price)

    def update_price(self, current_price: float) -> None:
        """Update current price and unrealized P&L.

        Args:
            current_price: Current market price
        """
        self.current_price = current_price

        if self.side == "long":
            # Long: profit when price goes up
            price_change = (current_price - self.entry_price) / self.entry_price
        else:  # short
            # Short: profit when price goes down
            price_change = (self.entry_price - current_price) / self.entry_price

        self.unrealized_pnl = self.size * price_change

    def calculate_pnl(self, exit_price: float) -> float:
        """Calculate realized P&L for position exit.

        Args:
            exit_price: Price at which position is closed

        Returns:
            Realized profit/loss
        """
        if self.side == "long":
            price_change = (exit_price - self.entry_price) / self.entry_price
        else:  # short
            price_change = (self.entry_price - exit_price) / self.entry_price

        return self.size * price_change - self.fees_paid

    def close(self, exit_price: float, fees: float = 0.0) -> float:
        """Close the position and calculate final P&L.

        Args:
            exit_price: Price at which position is closed
            fees: Trading fees for the exit

        Returns:
            Final realized P&L
        """
        self.exit_price = exit_price
        self.exit_time = datetime.now()
        self.fees_paid += fees
        self.realized_pnl = self.calculate_pnl(exit_price)
        self.unrealized_pnl = 0.0

        return self.realized_pnl

    @property
    def is_open(self) -> bool:
        """Check if position is still open."""
        return self.exit_time is None

    @property
    def current_value(self) -> float:
        """Get current market value of position."""
        return self.quantity * self.current_price

    @property
    def pnl_percentage(self) -> float:
        """Get P&L as percentage of initial size."""
        if self.size == 0:
            return 0.0

        pnl = self.realized_pnl if not self.is_open else self.unrealized_pnl
        return (pnl / self.size) * 100

    def __repr__(self) -> str:
        """String representation of position."""
        status = "OPEN" if self.is_open else "CLOSED"
        pnl = self.unrealized_pnl if self.is_open else self.realized_pnl
        return (f"Position({status} {self.side} {self.symbol}: "
                f"${self.size:.2f} @ ${self.entry_price:.2f}, "
                f"P&L: ${pnl:+.2f} ({self.pnl_percentage:+.2f}%))")