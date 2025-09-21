"""Order execution implementations."""

from abc import ABC, abstractmethod
from typing import Optional, Dict
from datetime import datetime
from loguru import logger

from ..trading.models import Order, Fill, OrderSide, OrderType
from ..data.sources.base import DataSource


class Executor(ABC):
    """Abstract base class for order execution."""

    @abstractmethod
    async def execute_order(self, order: Order) -> Fill:
        """Execute an order and return fill details.

        Args:
            order: Order to execute

        Returns:
            Fill details

        Raises:
            ExecutionError: If order cannot be executed
        """
        pass


class ExecutionError(Exception):
    """Exception raised when order execution fails."""
    pass


class MockExecutor(Executor):
    """Mock executor for backtesting and paper trading.

    This executor simulates order fills using either historical
    or live price data, without actually placing real orders.
    """

    def __init__(
        self,
        datasource: DataSource,
        slippage_bps: float = 10.0,  # Basis points (0.1%)
        fee_bps: float = 10.0,  # Basis points (0.1%)
        fill_rate: float = 1.0,  # Percentage of order filled
        use_bid_ask: bool = True  # Use bid/ask if available
    ):
        """Initialize mock executor.

        Args:
            datasource: Data source for price information
            slippage_bps: Slippage in basis points
            fee_bps: Trading fees in basis points
            fill_rate: Percentage of order that gets filled (0-1)
            use_bid_ask: Whether to use bid/ask prices if available
        """
        self.datasource = datasource
        self.slippage_pct = slippage_bps / 10000.0
        self.fee_pct = fee_bps / 10000.0
        self.fill_rate = fill_rate
        self.use_bid_ask = use_bid_ask

        logger.info(
            f"MockExecutor initialized with {slippage_bps}bps slippage, "
            f"{fee_bps}bps fees, {fill_rate:.0%} fill rate"
        )

    async def execute_order(self, order: Order) -> Fill:
        """Execute a mock order using datasource prices.

        Args:
            order: Order to execute

        Returns:
            Simulated fill

        Raises:
            ExecutionError: If cannot get price data
        """
        try:
            # Get current price data
            price_data = await self.datasource.get_current_price(order.symbol)

            if not price_data:
                raise ExecutionError(f"No price data available for {order.symbol}")

            # Determine fill price
            fill_price = await self._calculate_fill_price(order, price_data.price, price_data.bid, price_data.ask)

            # Calculate executed size (may be partial)
            executed_size = order.size * self.fill_rate

            # Calculate fees
            fees = executed_size * self.fee_pct

            # Create fill
            fill = Fill(
                order=order,
                executed_price=fill_price,
                executed_size=executed_size,
                fees=fees,
                timestamp=datetime.now()
            )

            # Log execution
            logger.debug(
                f"Mock executed {order.side.value} order for {order.symbol}: "
                f"${executed_size:.2f} @ ${fill_price:.2f} "
                f"(slippage: ${fill.slippage:.2f}, fees: ${fees:.2f})"
            )

            return fill

        except Exception as e:
            logger.error(f"Failed to execute order for {order.symbol}: {e}")
            raise ExecutionError(f"Order execution failed: {e}")

    async def _calculate_fill_price(
        self,
        order: Order,
        mid_price: float,
        bid_price: Optional[float],
        ask_price: Optional[float]
    ) -> float:
        """Calculate the fill price including slippage.

        Args:
            order: Order being executed
            mid_price: Mid market price
            bid_price: Current bid price (optional)
            ask_price: Current ask price (optional)

        Returns:
            Fill price including slippage
        """
        # Start with mid price
        base_price = mid_price

        # Use bid/ask if available and enabled
        if self.use_bid_ask and bid_price and ask_price:
            if order.side == OrderSide.BUY:
                # Buying at ask
                base_price = ask_price
            else:
                # Selling at bid
                base_price = bid_price

        # Apply slippage
        if order.side == OrderSide.BUY:
            # Buying: price goes up (worse)
            fill_price = base_price * (1 + self.slippage_pct)
        else:
            # Selling: price goes down (worse)
            fill_price = base_price * (1 - self.slippage_pct)

        # Handle limit orders
        if order.order_type == OrderType.LIMIT and order.limit_price:
            if order.side == OrderSide.BUY:
                # Don't pay more than limit
                fill_price = min(fill_price, order.limit_price)
            else:
                # Don't sell for less than limit
                fill_price = max(fill_price, order.limit_price)

        return fill_price

    async def get_execution_cost(self, order: Order) -> Dict[str, float]:
        """Estimate execution costs for an order.

        Args:
            order: Order to estimate

        Returns:
            Dict with estimated costs
        """
        try:
            price_data = await self.datasource.get_current_price(order.symbol)

            if not price_data:
                raise ValueError("No price data available")

            # Calculate expected fill price
            expected_price = await self._calculate_fill_price(
                order,
                price_data.price,
                price_data.bid,
                price_data.ask
            )

            # Calculate costs
            slippage_cost = abs(expected_price - price_data.price) * (order.size / price_data.price)
            fee_cost = order.size * self.fee_pct
            total_cost = slippage_cost + fee_cost

            return {
                "expected_price": expected_price,
                "slippage_cost": slippage_cost,
                "fee_cost": fee_cost,
                "total_cost": total_cost,
                "cost_pct": (total_cost / order.size) * 100
            }

        except Exception as e:
            logger.error(f"Failed to estimate execution cost: {e}")
            raise ValueError(f"Failed to estimate execution cost: {e}")


class BacktestExecutor(MockExecutor):
    """Specialized executor for backtesting with historical data.

    This executor ensures that fills use historical prices at the
    correct simulated time, not current prices.
    """

    def __init__(
        self,
        datasource: DataSource,
        slippage_bps: float = 10.0,
        fee_bps: float = 10.0,
        fill_rate: float = 1.0,
        use_orderbook: bool = False
    ):
        """Initialize backtest executor.

        Args:
            datasource: BacktestDataSource with historical data
            slippage_bps: Slippage in basis points
            fee_bps: Trading fees in basis points
            fill_rate: Percentage of order that gets filled
            use_orderbook: Whether to use historical orderbook data
        """
        super().__init__(datasource, slippage_bps, fee_bps, fill_rate, use_bid_ask=use_orderbook)
        self.use_orderbook = use_orderbook

        logger.info("BacktestExecutor initialized for historical data execution")

    async def execute_order(self, order: Order) -> Fill:
        """Execute order using historical prices at current simulation time.

        Args:
            order: Order to execute

        Returns:
            Fill with historical prices

        Raises:
            ExecutionError: If no historical data available
        """
        # Ensure we're using historical prices
        # The datasource should be a BacktestDataSource with current_time set
        if not hasattr(self.datasource, 'current_time'):
            logger.warning("BacktestExecutor used without BacktestDataSource")

        return await super().execute_order(order)