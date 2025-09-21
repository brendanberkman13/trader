"""Trading session orchestrator."""

import asyncio
from typing import Dict, List, Optional, Type, Any
from datetime import datetime, timedelta
from loguru import logger

from ..strategies.baseStrategy import BaseStrategy
from ..portfolio.manager import PortfolioManager, PortfolioStats
from ..execution.executor import Executor, MockExecutor, BacktestExecutor
from ..data.sources.base import DataSource
from ..data.sources.backtest import BacktestDataSource
from ..trading.models import Signal


class TradingSession:
    """Orchestrates trading strategies, portfolio management, and execution."""

    def __init__(
        self,
        datasource: DataSource,
        capital: float = 10000.0,
        executor_type: str = 'mock',
        executor_params: Optional[Dict[str, Any]] = None,
        quiet_mode: bool = False
    ):
        """Initialize trading session.

        Args:
            datasource: Data source for market data
            capital: Initial capital
            executor_type: Type of executor ('mock', 'backtest')
            executor_params: Additional parameters for executor
        """
        self.datasource = datasource
        self.portfolio = PortfolioManager(initial_capital=capital)

        # Create executor
        executor_params = executor_params or {}
        self.executor = self._create_executor(executor_type, executor_params)

        # Strategy management
        self.strategies: Dict[str, BaseStrategy] = {}

        # Session state
        self.is_running = False
        self.iteration_count = 0
        self.start_time: Optional[datetime] = None
        self.end_time: Optional[datetime] = None
        self.quiet_mode = quiet_mode

        logger.info(
            f"TradingSession initialized with ${capital:.2f} capital, "
            f"{executor_type} executor, {type(datasource).__name__} datasource"
        )

    def _create_executor(self, executor_type: str, params: Dict[str, Any]) -> Executor:
        """Create the appropriate executor.

        Args:
            executor_type: Type of executor to create
            params: Executor parameters

        Returns:
            Executor instance

        Raises:
            ValueError: If executor_type is unknown
        """
        if executor_type == 'mock':
            return MockExecutor(self.datasource, **params)
        elif executor_type == 'backtest':
            return BacktestExecutor(self.datasource, **params)
        else:
            raise ValueError(f"Unknown executor type: {executor_type}")

    def add_strategy(
        self,
        strategy_class: Type[BaseStrategy],
        name: Optional[str] = None,
        allocation: float = 1.0,
        **kwargs
    ) -> None:
        """Add a strategy to the session.

        Args:
            strategy_class: Strategy class to instantiate
            name: Optional name for the strategy
            allocation: Capital allocation percentage (0-1)
            **kwargs: Additional arguments for strategy initialization
        """
        # Create strategy instance with datasource
        strategy = strategy_class(datasource=self.datasource, **kwargs)

        # Use provided name or strategy's own name
        strategy_name = name or strategy.name

        # Check for duplicate
        if strategy_name in self.strategies:
            raise ValueError(f"Strategy '{strategy_name}' already exists")

        # Add to strategies
        self.strategies[strategy_name] = strategy

        # Register with portfolio
        self.portfolio.register_strategy(strategy_name, allocation)

        logger.info(
            f"Added strategy '{strategy_name}' with {allocation:.0%} allocation"
        )

    async def run(
        self,
        iterations: Optional[int] = None,
        interval_seconds: float = 1.0,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> None:
        """Run the trading session.

        Args:
            iterations: Number of iterations (None for continuous)
            interval_seconds: Seconds between iterations
            start_time: Start time for backtesting
            end_time: End time for backtesting
        """
        if not self.strategies:
            raise ValueError("No strategies added to session")

        self.is_running = True
        self.start_time = start_time or datetime.now()
        self.end_time = end_time
        self.iteration_count = 0

        # Setup backtest datasource if needed
        if isinstance(self.datasource, BacktestDataSource):
            if start_time:
                self.datasource.set_current_time(start_time)
            logger.info(f"Starting backtest from {start_time} to {end_time}")

        logger.info("=" * 60)
        logger.info("TRADING SESSION STARTED")
        logger.info(f"Strategies: {list(self.strategies.keys())}")
        logger.info(f"Capital: ${self.portfolio.initial_capital:,.2f}")
        logger.info("=" * 60)

        try:
            while self.is_running:
                # Check iteration limit
                if iterations and self.iteration_count >= iterations:
                    logger.info(f"Reached iteration limit ({iterations})")
                    break

                # Check end time for backtesting
                if isinstance(self.datasource, BacktestDataSource):
                    if end_time and self.datasource.current_time and self.datasource.current_time >= end_time:
                        logger.info(f"Reached backtest end time: {end_time}")
                        break

                # Run one iteration
                await self._run_iteration()

                # Advance time for backtesting
                if isinstance(self.datasource, BacktestDataSource):
                    self.datasource.advance_time(int(interval_seconds / 60))

                # Sleep for live/paper trading
                else:
                    await asyncio.sleep(interval_seconds)

                self.iteration_count += 1

        except KeyboardInterrupt:
            logger.info("Session interrupted by user")

        except Exception as e:
            logger.error(f"Session error: {e}")
            raise

        finally:
            self.is_running = False
            self._print_final_stats()

    async def _run_iteration(self) -> None:
        """Run a single iteration of the trading loop."""
        timestamp = datetime.now()

        # For backtesting, use simulated time
        if isinstance(self.datasource, BacktestDataSource) and self.datasource.current_time:
            timestamp = self.datasource.current_time

        logger.debug(f"\n--- Iteration {self.iteration_count + 1} [{timestamp.strftime('%Y-%m-%d %H:%M:%S')}] ---")

        # 1. Collect signals from all strategies
        signals = await self._collect_signals()

        if signals and not self.quiet_mode:
            logger.info(f"Collected {len(signals)} signals from strategies")

        # 2. Process signals through portfolio manager
        orders = self.portfolio.process_signals(signals)

        if orders and not self.quiet_mode:
            logger.info(f"Generated {len(orders)} orders from signals")

        # 3. Execute orders
        for order in orders:
            try:
                fill = await self.executor.execute_order(order)
                self.portfolio.process_fill(fill)

            except Exception as e:
                logger.error(f"Failed to execute order for {order.symbol}: {e}")

        # 4. Update portfolio prices
        await self._update_portfolio_prices()

        # 5. Show progress and log portfolio status
        if isinstance(self.datasource, BacktestDataSource) and self.quiet_mode:
            self._show_progress()
        elif self.iteration_count % 10 == 0:
            self._log_portfolio_status()

    async def _collect_signals(self) -> List[Signal]:
        """Collect signals from all strategies.

        Returns:
            List of signals
        """
        signals = []

        for strategy_name, strategy in self.strategies.items():
            try:
                # Get signals from strategy (now returns List[Signal])
                strategy_signals = await strategy.calculate_signal()

                if strategy_signals:
                    for signal in strategy_signals:
                        # Ensure signal has strategy ID
                        signal.strategy_id = strategy_name
                        signals.append(signal)

                        if not self.quiet_mode:
                            logger.debug(
                                f"Signal from {strategy_name}: {signal.signal.value} "
                                f"{signal.symbol} (strength: {signal.strength:.2f})"
                            )

            except Exception as e:
                logger.error(f"Error getting signal from {strategy_name}: {e}")

        return signals

    async def _update_portfolio_prices(self) -> None:
        """Update current prices for all portfolio positions."""
        if not self.portfolio.positions:
            return

        prices = {}
        for symbol in self.portfolio.positions.keys():
            try:
                price_data = await self.datasource.get_current_price(symbol)
                if price_data:
                    prices[symbol] = price_data.price

            except Exception as e:
                logger.error(f"Failed to get price for {symbol}: {e}")

        if prices:
            self.portfolio.update_prices(prices)

    def _show_progress(self) -> None:
        """Show progress indicator for backtesting in quiet mode."""
        if not isinstance(self.datasource, BacktestDataSource):
            return

        # Show progress every 50 iterations
        if self.iteration_count % 50 == 0:
            progress = self.datasource.get_progress()
            if progress is not None:
                # Create progress bar
                bar_length = 30
                filled_length = int(bar_length * progress / 100)
                bar = '█' * filled_length + '░' * (bar_length - filled_length)

                # Get current stats for display
                stats = self.portfolio.get_stats()
                pnl_pct = ((stats.total_value - self.portfolio.initial_capital) / self.portfolio.initial_capital) * 100

                print(f"\rProgress: |{bar}| {progress:.1f}% | Trades: {stats.num_trades} | P&L: {pnl_pct:+.1f}%", end='', flush=True)

        # Final newline when complete
        if self.iteration_count > 0 and hasattr(self.datasource, 'get_progress'):
            progress = self.datasource.get_progress()
            if progress and progress >= 99.9:
                print()  # New line after progress bar

    def _log_portfolio_status(self) -> None:
        """Log current portfolio status."""
        stats = self.portfolio.get_stats()

        logger.info("📊 Portfolio Status:")
        logger.info(f"  Total Value: ${stats.total_value:,.2f}")
        logger.info(f"  Cash: ${stats.cash:,.2f}")
        logger.info(f"  Positions: {stats.num_positions}")

        if stats.total_pnl != 0:
            pnl_pct = (stats.total_pnl / self.portfolio.initial_capital) * 100
            pnl_emoji = "🟢" if stats.total_pnl > 0 else "🔴"
            logger.info(f"  {pnl_emoji} Total P&L: ${stats.total_pnl:+,.2f} ({pnl_pct:+.2f}%)")

        if stats.num_trades > 0:
            logger.info(f"  Win Rate: {stats.win_rate:.1%} ({stats.winning_trades}/{stats.num_trades})")

    def _print_final_stats(self) -> None:
        """Print final session statistics."""
        logger.info("\n" + "=" * 60)
        logger.info("TRADING SESSION COMPLETED")
        logger.info("=" * 60)

        stats = self.portfolio.get_stats()

        # Performance summary
        total_return = ((stats.total_value - self.portfolio.initial_capital) /
                       self.portfolio.initial_capital) * 100

        logger.info(f"Initial Capital: ${self.portfolio.initial_capital:,.2f}")
        logger.info(f"Final Value: ${stats.total_value:,.2f}")
        logger.info(f"Total Return: {total_return:+.2f}%")

        # Trading summary
        logger.info(f"\nTrading Summary:")
        logger.info(f"  Total Trades: {stats.num_trades}")
        logger.info(f"  Winning Trades: {stats.winning_trades}")
        logger.info(f"  Losing Trades: {stats.losing_trades}")

        if stats.num_trades > 0:
            logger.info(f"  Win Rate: {stats.win_rate:.1%}")
            if stats.avg_win != 0:
                logger.info(f"  Avg Win: ${stats.avg_win:+,.2f}")
            if stats.avg_loss != 0:
                logger.info(f"  Avg Loss: ${stats.avg_loss:+,.2f}")

        # P&L breakdown
        logger.info(f"\nP&L Breakdown:")
        logger.info(f"  Realized P&L: ${stats.realized_pnl:+,.2f}")
        logger.info(f"  Unrealized P&L: ${stats.unrealized_pnl:+,.2f}")
        logger.info(f"  Total P&L: ${stats.total_pnl:+,.2f}")
        logger.info(f"  Total Fees Paid: ${self.portfolio.fees_paid:+,.2f}")

        # Debug calculation
        logger.info(f"\nDebug Calculation:")
        logger.info(f"  Cash: ${stats.cash:+,.2f}")
        logger.info(f"  Positions Value: ${stats.positions_value:+,.2f}")
        logger.info(f"  Total Value: ${stats.total_value:+,.2f}")
        logger.info(f"  Initial Capital: ${self.portfolio.initial_capital:+,.2f}")
        logger.info(f"  Actual Gain: ${stats.total_value - self.portfolio.initial_capital:+,.2f}")
        logger.info(f"  P&L + Fees: ${stats.total_pnl - self.portfolio.fees_paid:+,.2f}")

        # Open positions
        if stats.num_positions > 0:
            logger.info(f"\nOpen Positions: {stats.num_positions}")
            for symbol, position in self.portfolio.get_all_positions().items():
                logger.info(f"  {symbol}: ${position.size:.2f} @ ${position.entry_price:.2f}")

        # Session info
        runtime = self.iteration_count
        if self.start_time:
            if isinstance(self.datasource, BacktestDataSource):
                runtime = f"{self.iteration_count} iterations"
            else:
                elapsed = datetime.now() - self.start_time
                runtime = f"{elapsed.total_seconds() / 60:.1f} minutes"

        logger.info(f"\nSession Info:")
        logger.info(f"  Iterations: {self.iteration_count}")
        logger.info(f"  Runtime: {runtime}")

    def get_performance_stats(self) -> PortfolioStats:
        """Get current performance statistics.

        Returns:
            Portfolio statistics
        """
        return self.portfolio.get_stats()

    def stop(self) -> None:
        """Stop the trading session."""
        self.is_running = False
        logger.info("Stopping trading session...")

    def reset(self) -> None:
        """Reset the session to initial state."""
        self.portfolio.reset()
        self.iteration_count = 0
        self.start_time = None
        self.end_time = None

        # Reset backtest datasource if applicable
        if isinstance(self.datasource, BacktestDataSource):
            self.datasource.reset()

        logger.info("Session reset to initial state")