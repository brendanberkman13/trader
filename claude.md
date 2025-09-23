# Crypto Trading System

A sophisticated quantitative trading system for cryptocurrency markets with backtesting capabilities, real-time data collection, and modular strategy development.

## Project Overview

This is an async Python trading system designed for cryptocurrency markets. It provides a complete framework for developing, backtesting, and running trading strategies with proper risk management and portfolio tracking.

### Key Features
- Real-time and historical data collection from multiple exchanges
- Modular strategy framework with base classes for easy development
- Comprehensive backtesting engine with realistic simulation
- Portfolio management with position tracking and P&L calculation
- Session-based trading with performance analytics
- Support for multiple concurrent strategies with capital allocation
- Mock and live execution capabilities

## Technical Stack

- **Language**: Python 3.11+
- **Package Manager**: UV (fast Python package installer)
- **Async Framework**: asyncio for concurrent operations
- **Database**: SQLite (247MB trading.db with historical data)
- **Data Processing**: Polars (high-performance dataframe library)
- **Exchange API**: CCXT (unified cryptocurrency exchange interface)
- **Logging**: Loguru (structured logging with levels)
- **HTTP Client**: aiohttp for async API calls

## Project Structure

```
trader/
├── src/
│   ├── data/
│   │   ├── clients/         # Exchange API clients
│   │   │   ├── base.py     # Base client interface
│   │   │   └── Binance/    # Binance-specific implementation
│   │   ├── collector/       # Data collection modules
│   │   │   ├── baseCollector.py
│   │   │   ├── priceCollector.py
│   │   │   └── runCollectors.py
│   │   ├── sources/         # Data source abstractions
│   │   │   ├── base.py     # DataSource interface
│   │   │   ├── live.py     # Real-time data
│   │   │   └── backtest.py # Historical data replay
│   │   └── storage/
│   │       └── database.py # SQLite operations
│   │
│   ├── strategies/          # Trading strategies
│   │   ├── baseStrategy.py # Abstract base class
│   │   └── ratioStrategy.py # Example implementation
│   │
│   ├── portfolio/           # Portfolio management
│   │   ├── manager.py      # Position & P&L tracking
│   │   └── risk/           # Risk management (new)
│   │
│   ├── execution/           # Order execution
│   │   └── executor.py     # Mock/Backtest/Live executors
│   │
│   ├── trading/             # Core trading logic
│   │   ├── models.py       # Signal, Order, Fill models
│   │   └── session.py      # Trading orchestration
│   │
│   └── utils/
│       └── downloadHistorical.py # Data downloading utilities
│
├── tests/                   # Unit tests
├── notebooks/               # Research & analysis
├── data/
│   └── trading.db          # SQLite database (247MB)
├── playground.py           # Quick testing script
├── pyproject.toml          # UV package configuration
└── .env                    # API keys (not in git)
```

## Core Architecture

### 1. Data Layer (`src/data/`)

**Data Flow**: Exchange API → Client → Collector → Storage → DataSource → Strategy

- **Clients**: Abstract exchange connections using CCXT
- **Collectors**: Continuous data collection with configurable intervals
- **Sources**: Unified interface for live and historical data
- **Storage**: SQLite with potential PostgreSQL migration path

### 2. Strategy Layer (`src/strategies/`)

All strategies inherit from `BaseStrategy`:
```python
class BaseStrategy(ABC):
    - datasource: DataSource connection
    - signals_history: Track all generated signals
    - calculate_signal(): Abstract method returning List[Signal]
```

### 3. Portfolio Management (`src/portfolio/`)

`PortfolioManager` handles:
- Position tracking (open/closed)
- P&L calculation (realized/unrealized)
- Strategy allocation (percentage-based)
- Risk limits and position sizing
- Fee tracking

### 4. Trading Session (`src/trading/`)

`TradingSession` orchestrates the entire trading loop:
1. Collect signals from all strategies
2. Process signals through portfolio manager
3. Generate and execute orders
4. Update portfolio with fills
5. Track performance metrics

### 5. Execution Layer (`src/execution/`)

Three execution modes:
- **MockExecutor**: Simulated fills for testing
- **BacktestExecutor**: Historical data replay
- **LiveExecutor**: Real exchange orders (future)

## Database Schema

SQLite database (`data/trading.db`) contains:

- **prices**: Real-time ticker data
- **candles**: OHLCV historical data
- **orderbook**: Market depth snapshots
- **sessions**: Trading session metadata
- **signals**: All generated trading signals
- **orders**: Order placement records
- **fills**: Execution confirmations
- **positions**: Position tracking
- **trades**: Completed round-trips

## Development Guidelines

### Import Pattern
Always use absolute imports from project root:
```python
from src.data.clients.Binance.binanceClient import BinanceClient
from src.strategies.baseStrategy import BaseStrategy
from src.trading.session import TradingSession
```

### Creating a New Strategy

1. Inherit from `BaseStrategy`
2. Implement `calculate_signal()` method
3. Return `List[Signal]` with proper strength values
4. Register with `TradingSession.add_strategy()`

Example:
```python
class MyStrategy(BaseStrategy):
    async def calculate_signal(self) -> List[Signal]:
        # Get data from self.datasource
        # Calculate indicators
        # Return signals
```

## Implemented Strategies

### BTC/ETH Ratio Mean Reversion Strategy (`ratioStrategy.py`)

This is a **statistical arbitrage pairs trading strategy** that exploits mean reversion in the price ratio between two correlated assets (default: BTC and ETH).

#### How It Works

1. **Ratio Calculation**: Continuously monitors the price ratio `BTC/ETH`
2. **Statistical Analysis**:
   - Calculates rolling mean and standard deviation over lookback period (default: 20)
   - Computes Z-score: `(current_ratio - mean) / std_dev`
3. **Signal Generation**:
   - **Entry**: When |Z-score| > 2.0 (configurable)
     - Z-score > 2.0: BTC expensive → SELL BTC, BUY ETH
     - Z-score < -2.0: ETH expensive → BUY BTC, SELL ETH
   - **Exit**: When |Z-score| < 0.5 (mean reversion complete)
4. **State Machine**: Tracks position state (NEUTRAL, LONG_B_SHORT_A, LONG_A_SHORT_B)

#### Key Parameters
- `symbol_a`: Numerator asset (default: BTC/USDT)
- `symbol_b`: Denominator asset (default: ETH/USDT)
- `lookback_periods`: Historical window for statistics (default: 20)
- `entry_threshold`: Z-score for opening positions (default: 2.0)
- `exit_threshold`: Z-score for closing positions (default: 0.5)

#### Trading Logic
```
High Z-score scenario (Z > 2.0):
- BTC/ETH ratio is abnormally high
- BTC is overvalued relative to ETH
- Action: SELL BTC (short), BUY ETH (long)
- Profit when ratio normalizes (converges to mean)

Low Z-score scenario (Z < -2.0):
- BTC/ETH ratio is abnormally low
- ETH is overvalued relative to BTC
- Action: BUY BTC (long), SELL ETH (short)
- Profit when ratio normalizes (converges to mean)
```

#### Risk Characteristics
- **Market Neutral**: Long one asset, short another (hedged)
- **Mean Reversion Bet**: Assumes ratio will revert to historical mean
- **Correlation Risk**: Strategy fails if correlation breaks down
- **Requires Sufficient History**: Needs at least 20 data points to calculate statistics

#### Example Usage
```python
from src.strategies.ratioStrategy import RatioStrategy

# In TradingSession
session.add_strategy(
    RatioStrategy,
    name="btc_eth_pairs",
    allocation=0.5,
    symbol_a="BTC/USDT",
    symbol_b="ETH/USDT",
    lookback_periods=30,
    entry_threshold=2.5,
    exit_threshold=0.3
)
```

#### Performance Considerations
- Works best in ranging markets with stable correlations
- May underperform in strong trending markets
- Requires careful position sizing due to dual-asset exposure
- Transaction costs important due to 4 trades per round trip

### Running the System

```bash
# Install dependencies
uv sync

# Run data collectors
python -m src.data.collector.runCollectors

# Run a backtest
python playground.py  # See example session setup

# Run with specific strategy
python run_strategy.py --strategy ratio --capital 10000
```

### Testing Approach

1. **Unit Tests**: Test individual components in isolation
2. **Integration Tests**: Test component interactions
3. **Backtest First**: Always validate strategies on historical data
4. **Paper Trading**: Use MockExecutor before going live
5. **Session Comparison**: Use session_id to A/B test parameters

## Configuration

### Environment Variables (.env)
```
BINANCE_API_KEY=your_key_here
BINANCE_API_SECRET=your_secret_here
DATABASE_PATH=data/trading.db
LOG_LEVEL=INFO
```

### Strategy Parameters
- Pass parameters during initialization
- Use session_id for parameter comparison
- Track performance per configuration

### Risk Limits
- Set per-strategy allocation percentages
- Define maximum position sizes
- Implement stop-loss/take-profit levels

## Best Practices

### Code Style
- Type hints on all functions
- Async/await for I/O operations
- Loguru for structured logging
- Handle exceptions gracefully
- Document complex logic

### Performance
- Use Polars over Pandas for data operations
- Batch database operations
- Cache frequently accessed data
- Profile bottlenecks with cProfile

### Safety
- Never commit API keys
- Validate all external data
- Use paper trading extensively
- Implement circuit breakers
- Log all trading decisions

## Common Tasks

### Add a New Exchange
1. Create client in `src/data/clients/`
2. Inherit from base client
3. Implement required methods
4. Add to collector configuration

### Optimize a Strategy
1. Run backtests with different parameters
2. Compare session_id results
3. Analyze win rate and P&L metrics
4. Validate on out-of-sample data

### Debug Issues
1. Check logs with appropriate level
2. Verify database connectivity
3. Confirm API credentials
4. Test components in isolation
5. Use playground.py for quick tests

## Future Enhancements

- [ ] Live trading execution
- [ ] WebSocket real-time data
- [ ] Advanced risk metrics (Sharpe, Sortino)
- [ ] ML-based signal generation
- [ ] Multi-exchange arbitrage
- [ ] Portfolio rebalancing
- [ ] Telegram/Discord notifications
- [ ] Web dashboard for monitoring

## Troubleshooting

### Common Issues

1. **Import Errors**: Ensure running from project root
2. **Database Lock**: Close other connections
3. **API Rate Limits**: Implement exponential backoff
4. **Memory Issues**: Use data generators for large datasets
5. **Async Errors**: Properly await all coroutines

### Debug Mode

Enable detailed logging:
```python
from loguru import logger
logger.add("debug.log", level="DEBUG")
```

## Important Notes

- Always run from the project root directory
- Use UV for package management (faster than pip)
- SQLite is sufficient for development; consider PostgreSQL for production
- The 247MB trading.db contains valuable historical data - backup regularly
- Session tracking enables systematic strategy comparison
- Fees are tracked but may need exchange-specific adjustments

## Quick Start Example

```python
import asyncio
from src.trading.session import TradingSession
from src.data.sources.backtest import BacktestDataSource
from src.strategies.ratioStrategy import RatioStrategy

async def main():
    # Setup datasource
    datasource = BacktestDataSource(database_path="data/trading.db")

    # Create session
    session = TradingSession(
        datasource=datasource,
        capital=10000,
        executor_type='backtest'
    )

    # Add strategy
    session.add_strategy(
        RatioStrategy,
        name="btc_eth_ratio",
        allocation=1.0
    )

    # Run backtest
    await session.run(
        iterations=1000,
        start_time=datetime(2024, 1, 1),
        end_time=datetime(2024, 9, 1)
    )

if __name__ == "__main__":
    asyncio.run(main())
```