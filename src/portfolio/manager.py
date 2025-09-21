"""Portfolio manager for handling positions and capital allocation."""

from typing import Dict, List, Optional, Set, Tuple
from datetime import datetime
from dataclasses import dataclass, field
from loguru import logger

from ..trading.models import Signal, Order, Fill, Position, OrderSide, SignalType


@dataclass
class PortfolioStats:
    """Portfolio performance statistics."""
    total_value: float
    cash: float
    positions_value: float
    unrealized_pnl: float
    realized_pnl: float
    total_pnl: float
    num_positions: int
    num_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    avg_win: float
    avg_loss: float
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0


class PortfolioManager:
    """Manages portfolio positions, capital allocation, and risk."""

    def __init__(
        self,
        initial_capital: float = 10000.0,
        max_position_size_pct: float = 0.1,  # Max 10% per position
        max_positions: int = 10,
        position_sizing: str = "equal"  # 'equal', 'signal_strength', 'volatility'
    ):
        """Initialize portfolio manager.

        Args:
            initial_capital: Starting capital
            max_position_size_pct: Maximum size as percentage of capital
            max_positions: Maximum number of concurrent positions
            position_sizing: Position sizing method
        """
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.max_position_size_pct = max_position_size_pct
        self.max_positions = max_positions
        self.position_sizing = position_sizing

        # Position tracking
        self.positions: Dict[str, Position] = {}  # symbol -> Position
        self.closed_positions: List[Position] = []

        # Strategy tracking
        self.registered_strategies: Set[str] = set()
        self.strategy_allocations: Dict[str, float] = {}  # strategy_id -> allocation %

        # Performance tracking
        self.realized_pnl = 0.0
        self.fees_paid = 0.0
        self.trade_count = 0
        self.equity_curve: List[Tuple[datetime, float]] = [(datetime.now(), initial_capital)]

    def register_strategy(self, strategy_id: str, allocation: float = 1.0) -> None:
        """Register a strategy with the portfolio.

        Args:
            strategy_id: Unique strategy identifier
            allocation: Allocation percentage (0-1)
        """
        if allocation <= 0 or allocation > 1:
            raise ValueError(f"Allocation must be between 0 and 1, got {allocation}")

        self.registered_strategies.add(strategy_id)
        self.strategy_allocations[strategy_id] = allocation

        logger.debug(f"Registered strategy '{strategy_id}' with {allocation:.0%} allocation")

    def process_signals(self, signals: List[Signal]) -> List[Order]:
        """Process signals and generate orders.

        Args:
            signals: List of trading signals from strategies

        Returns:
            List of orders to be executed
        """
        orders = []

        # Sort signals by strength (strongest first)
        sorted_signals = sorted(signals, key=lambda s: s.strength, reverse=True)

        for signal in sorted_signals:
            # Skip if strategy not registered
            if signal.strategy_id not in self.registered_strategies:
                logger.warning(f"Signal from unregistered strategy: {signal.strategy_id}")
                continue

            # Skip HOLD signals
            if signal.signal == SignalType.HOLD:
                continue

            # Check if we already have a position in this symbol
            if signal.symbol in self.positions:
                # Check if this is an exit signal for existing position
                position = self.positions[signal.symbol]
                if self._is_exit_signal(signal, position):
                    order = self._create_exit_order(signal, position)
                    if order:
                        orders.append(order)
                else:
                    logger.debug(f"Already have position in {signal.symbol}, skipping signal")
                continue

            # Check if we can open new position
            if len(self.positions) >= self.max_positions:
                logger.warning(f"Maximum positions ({self.max_positions}) reached, skipping signal")
                continue

            # Create entry order
            order = self._create_entry_order(signal)
            if order:
                orders.append(order)

        return orders

    def _create_entry_order(self, signal: Signal) -> Optional[Order]:
        """Create an entry order from a signal.

        Args:
            signal: Trading signal

        Returns:
            Order or None if cannot create
        """
        # Calculate position size
        position_size = self._calculate_position_size(signal)

        if position_size <= 0:
            logger.warning(f"Position size is 0 for {signal.symbol}, skipping")
            return None

        # Check if we have enough cash
        if position_size > self.cash:
            # Reduce to available cash
            position_size = self.cash * 0.99  # Leave some buffer

            if position_size < 100:  # Minimum position size
                logger.warning(f"Insufficient cash for {signal.symbol} order")
                return None

        # Create order
        order_side = OrderSide.BUY if signal.signal == SignalType.BUY else OrderSide.SELL

        order = Order(
            symbol=signal.symbol,
            side=order_side,
            size=position_size,
            strategy_id=signal.strategy_id
        )

        logger.debug(
            f"Creating {order_side.value} order for {signal.symbol}: "
            f"${position_size:.2f} (signal strength: {signal.strength:.2f})"
        )

        return order

    def _create_exit_order(self, signal: Signal, position: Position) -> Optional[Order]:
        """Create an exit order for an existing position.

        Args:
            signal: Trading signal
            position: Existing position to exit

        Returns:
            Exit order or None
        """
        # Determine order side (opposite of position)
        order_side = OrderSide.SELL if position.side == "long" else OrderSide.BUY

        order = Order(
            symbol=position.symbol,
            side=order_side,
            size=position.size,  # Exit full position
            strategy_id=position.strategy_id
        )

        logger.debug(f"Creating exit order for {position.symbol} position")

        return order

    def _is_exit_signal(self, signal: Signal, position: Position) -> bool:
        """Check if signal is an exit signal for the position.

        Args:
            signal: Trading signal
            position: Existing position

        Returns:
            True if this is an exit signal
        """
        # Long position exits on SELL signal
        if position.side == "long" and signal.signal == SignalType.SELL:
            return True

        # Short position exits on BUY signal
        if position.side == "short" and signal.signal == SignalType.BUY:
            return True

        return False

    def _calculate_position_size(self, signal: Signal) -> float:
        """Calculate position size based on signal and portfolio state.

        Args:
            signal: Trading signal

        Returns:
            Position size in dollars
        """
        # Get total portfolio value
        total_value = self.get_total_value()

        # Base size as percentage of portfolio
        base_size = total_value * self.max_position_size_pct

        # Apply strategy allocation
        if signal.strategy_id:
            strategy_allocation = self.strategy_allocations.get(signal.strategy_id, 1.0)
        else:
            strategy_allocation = 1.0
        base_size *= strategy_allocation

        # Apply position sizing method
        if self.position_sizing == "equal":
            # Equal size for all positions
            position_size = base_size

        elif self.position_sizing == "signal_strength":
            # Scale by signal strength
            position_size = base_size * signal.strength

        elif self.position_sizing == "volatility":
            # TODO: Implement volatility-based sizing
            position_size = base_size

        else:
            position_size = base_size

        # Ensure we don't exceed max position size
        max_size = total_value * self.max_position_size_pct
        position_size = min(position_size, max_size)

        return round(position_size, 2)

    def process_fill(self, fill: Fill) -> None:
        """Process an executed fill and update positions.

        Args:
            fill: Executed fill details
        """
        order = fill.order
        symbol = order.symbol

        # Check if this is closing an existing position
        if symbol in self.positions:
            position = self.positions[symbol]

            # Close the position
            realized_pnl = position.close(fill.executed_price, fill.fees)
            self.realized_pnl += realized_pnl
            self.fees_paid += fill.fees

            # Move to closed positions
            self.closed_positions.append(position)
            del self.positions[symbol]

            # Update cash
            self.cash += fill.net_size + realized_pnl

            logger.debug(
                f"Closed {position.side} position in {symbol}: "
                f"P&L ${realized_pnl:+.2f} ({position.pnl_percentage:+.2f}%)"
            )

        else:
            # Opening new position
            position_side = "long" if order.side == OrderSide.BUY else "short"

            # Calculate quantity
            quantity = fill.executed_size / fill.executed_price

            position = Position(
                symbol=symbol,
                strategy_id=order.strategy_id or "unknown",
                side=position_side,
                entry_price=fill.executed_price,
                size=fill.executed_size,
                quantity=quantity,
                fees_paid=fill.fees
            )

            self.positions[symbol] = position
            self.cash -= fill.executed_size + fill.fees
            self.fees_paid += fill.fees

            logger.debug(
                f"Opened {position_side} position in {symbol}: "
                f"${fill.executed_size:.2f} @ ${fill.executed_price:.2f}"
            )

        self.trade_count += 1
        self._update_equity_curve()

    def update_prices(self, prices: Dict[str, float]) -> None:
        """Update current prices for all positions.

        Args:
            prices: Dict of symbol -> current price
        """
        for symbol, position in self.positions.items():
            if symbol in prices:
                position.update_price(prices[symbol])

    def get_position(self, symbol: str) -> Optional[Position]:
        """Get position for a specific symbol.

        Args:
            symbol: Trading symbol

        Returns:
            Position or None if not found
        """
        return self.positions.get(symbol)

    def get_all_positions(self) -> Dict[str, Position]:
        """Get all open positions.

        Returns:
            Dict of symbol -> Position
        """
        return self.positions.copy()

    def get_strategy_positions(self, strategy_id: str) -> List[Position]:
        """Get all positions for a specific strategy.

        Args:
            strategy_id: Strategy identifier

        Returns:
            List of positions for the strategy
        """
        return [
            pos for pos in self.positions.values()
            if pos.strategy_id == strategy_id
        ]

    def get_available_capital(self) -> float:
        """Get available cash for new positions.

        Returns:
            Available cash amount
        """
        return self.cash

    def get_total_value(self) -> float:
        """Get total portfolio value (cash + positions).

        Returns:
            Total portfolio value
        """
        positions_value = sum(pos.current_value for pos in self.positions.values())
        return self.cash + positions_value

    def get_unrealized_pnl(self) -> float:
        """Get total unrealized P&L from open positions.

        Returns:
            Unrealized P&L
        """
        return sum(pos.unrealized_pnl for pos in self.positions.values())

    def get_stats(self) -> PortfolioStats:
        """Get comprehensive portfolio statistics.

        Returns:
            Portfolio statistics
        """
        total_value = self.get_total_value()
        positions_value = sum(pos.current_value for pos in self.positions.values())
        unrealized_pnl = self.get_unrealized_pnl()
        total_pnl = self.realized_pnl + unrealized_pnl

        # Calculate win rate
        winning_trades = sum(1 for pos in self.closed_positions if pos.realized_pnl > 0)
        losing_trades = sum(1 for pos in self.closed_positions if pos.realized_pnl < 0)
        total_closed = len(self.closed_positions)

        win_rate = winning_trades / total_closed if total_closed > 0 else 0.0

        # Calculate average win/loss
        wins = [pos.realized_pnl for pos in self.closed_positions if pos.realized_pnl > 0]
        losses = [pos.realized_pnl for pos in self.closed_positions if pos.realized_pnl < 0]

        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 0.0

        return PortfolioStats(
            total_value=total_value,
            cash=self.cash,
            positions_value=positions_value,
            unrealized_pnl=unrealized_pnl,
            realized_pnl=self.realized_pnl,
            total_pnl=total_pnl,
            num_positions=len(self.positions),
            num_trades=self.trade_count,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate=win_rate,
            avg_win=avg_win,
            avg_loss=avg_loss
        )

    def _update_equity_curve(self) -> None:
        """Update the equity curve with current portfolio value."""
        current_value = self.get_total_value()
        self.equity_curve.append((datetime.now(), current_value))

        # Keep only last 10000 points to avoid memory issues
        if len(self.equity_curve) > 10000:
            self.equity_curve = self.equity_curve[-10000:]

    def can_afford_order(self, order: Order) -> bool:
        """Check if we have enough capital for an order.

        Args:
            order: Order to check

        Returns:
            True if we can afford the order
        """
        return order.size <= self.cash

    def reset(self) -> None:
        """Reset portfolio to initial state."""
        self.cash = self.initial_capital
        self.positions.clear()
        self.closed_positions.clear()
        self.realized_pnl = 0.0
        self.fees_paid = 0.0
        self.trade_count = 0
        self.equity_curve = [(datetime.now(), self.initial_capital)]

        logger.debug("Portfolio reset to initial state")