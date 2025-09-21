# Crypto Trading System

A quantitative trading system for cryptocurrency markets, focusing on altcoins and market inefficiencies.

## Project Structure
```
trader/
├── src/
│   ├── data/
│   │   ├── clients/       # Exchange connections
│   │   ├── collector/     # Data collection
│   │   └── storage/       # Database operations
│   ├── strategies/        # Trading strategies
│   ├── risk/             # Risk management
│   ├── execution/        # Order execution
│   └── backtest/         # Backtesting engine
├── tests/                # Unit tests
├── notebooks/            # Research notebooks
└── data/
    └── trading.db       # SQLite database
```

## Technical Stack
- **Language**: Python 3.11+
- **Package Manager**: UV
- **Database**: SQLite (easily portable to PostgreSQL)
- **Data Processing**: Polars (faster than Pandas)
- **Exchange API**: CCXT
- **Logging**: Loguru
- **Async**: asyncio for concurrent operations

## Core Components

### Data Layer
- **Clients**: Exchange integrations (Binance, Coinbase)
- **Collectors**: Continuous price, candle, and orderbook collection
- **Storage**: Database with session tracking for A/B testing strategies

### Strategy Layer
- Base strategy framework with position tracking
- Strategies inherit from `BaseStrategy` class
- Session-based isolation for testing different parameters
- Paper trading and live trading support

### Database Schema
- `prices`: Real-time ticker data
- `candles`: OHLCV historical data
- `sessions`: Strategy test runs
- `trades`: Executed trades (paper or real)
- `signals`: All generated signals

## Running Commands
```bash
# Collect market data
python -m src.data.collector.run

# Run a strategy
python run_strategy.py

# Run tests
pytest tests/
```

## Key Design Decisions

1. **Session-based Testing**: Each strategy run gets a unique session_id for comparison
2. **Paper Trading First**: All trades marked with is_paper flag
3. **Modular Architecture**: Strategies, data, and execution are separate modules
4. **Async Operations**: Non-blocking I/O for real-time data collection
5. **Type Hints**: All functions use type annotations

## Import Pattern
Always run from project root directory:
```python
from src.data.clients.binance import BinanceClient
from src.strategies.base_strategy import BaseStrategy
from src.data.storage.database import Database
```

## Configuration
- Exchange API keys in `.env` file
- Strategy parameters passed at initialization
- Risk limits defined per strategy

## Data Requirements
- Minimum 20 data points for mean reversion strategies
- Collector runs every 30 seconds by default
- Historical data stored locally for backtesting