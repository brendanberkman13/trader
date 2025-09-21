"""Database module for storing market data."""

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any
import polars as pl
from loguru import logger
import uuid
import json


class Database:
    """SQLite database for market data storage."""
    
    def __init__(self, db_path: str = "data/trading.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_tables()
        logger.info(f"Database initialized at {self.db_path}")
    
    @contextmanager
    def get_connection(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # Enable column access by name
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Database error: {e}")
            raise
        finally:
            conn.close()
    
    def _init_tables(self):
        """Create tables if they don't exist."""
        with self.get_connection() as conn:
            # Prices table - stores ticker data
            conn.execute("""
                CREATE TABLE IF NOT EXISTS prices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    timestamp DATETIME NOT NULL,
                    bid REAL,
                    ask REAL,
                    last REAL NOT NULL,
                    volume_24h REAL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(symbol, timestamp)
                )
            """)
            
            # Candles table - stores OHLCV data
            conn.execute("""
                CREATE TABLE IF NOT EXISTS candles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    timestamp DATETIME NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume REAL NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(symbol, timeframe, timestamp)
                )
            """)
            
            # Order book snapshots - stores market depth
            conn.execute("""
                CREATE TABLE IF NOT EXISTS orderbook_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    timestamp DATETIME NOT NULL,
                    bids TEXT NOT NULL,  -- JSON string
                    asks TEXT NOT NULL,  -- JSON string
                    spread REAL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Sessions table - track different testing/trading sessions
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT,
                    strategies TEXT,  -- JSON list of strategy names
                    parameters TEXT,  -- JSON dict of parameters
                    is_live BOOLEAN DEFAULT 0,  -- 0 for test, 1 for live trading
                    started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    ended_at DATETIME,
                    total_pnl REAL DEFAULT 0,
                    trade_count INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'active'  -- active, completed, cancelled
                )
            """)
            
            # Trades table - stores executed trades (your bot's trades)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,  -- Links to sessions table
                    order_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    price REAL NOT NULL,
                    amount REAL NOT NULL,
                    fee REAL,
                    timestamp DATETIME NOT NULL,
                    strategy TEXT,
                    pnl REAL,
                    is_paper BOOLEAN DEFAULT 1,  -- 1 for paper, 0 for real
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (session_id) REFERENCES sessions(session_id),
                    UNIQUE(session_id, order_id)
                )
            """)
            
            # Signals table - track all signals (even if not traded)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    symbol TEXT NOT NULL,
                    signal_type TEXT NOT NULL,  -- BUY, SELL, HOLD
                    strength REAL,
                    price REAL,
                    reason TEXT,
                    strategy TEXT,
                    traded BOOLEAN DEFAULT 0,  -- Was this signal acted upon?
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
                )
            """)
            
            # Create indexes for faster queries
            conn.execute("CREATE INDEX IF NOT EXISTS idx_prices_symbol_time ON prices(symbol, timestamp DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_candles_symbol_time ON candles(symbol, timeframe, timestamp DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades(timestamp DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_session ON trades(session_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_signals_session ON signals(session_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status)")
            
            logger.debug("Database tables initialized")
    
    # ============= ORIGINAL METHODS =============
    
    def save_ticker(self, ticker) -> bool:
        """Save a ticker to the database."""
        try:
            with self.get_connection() as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO prices 
                    (symbol, timestamp, bid, ask, last, volume_24h)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    ticker.symbol,
                    ticker.timestamp,
                    ticker.bid,
                    ticker.ask,
                    ticker.last,
                    ticker.volume_24h
                ))
            logger.debug(f"Saved ticker for {ticker.symbol}")
            return True
        except Exception as e:
            logger.error(f"Failed to save ticker: {e}")
            return False
    
    def save_candles(self, symbol: str, timeframe: str, candles: List) -> int:
        """Save multiple candles to the database. Returns count saved."""
        saved_count = 0
        with self.get_connection() as conn:
            for candle in candles:
                try:
                    conn.execute("""
                        INSERT OR REPLACE INTO candles 
                        (symbol, timeframe, timestamp, open, high, low, close, volume)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        symbol,
                        timeframe,
                        candle.timestamp,
                        candle.open,
                        candle.high,
                        candle.low,
                        candle.close,
                        candle.volume
                    ))
                    saved_count += 1
                except Exception as e:
                    logger.warning(f"Skipped candle: {e}")
        
        logger.info(f"Saved {saved_count}/{len(candles)} candles for {symbol} {timeframe}")
        return saved_count
    
    def save_orderbook(self, orderbook, symbol: str) -> bool:
        """Save an orderbook snapshot."""
        try:
            # Calculate spread
            spread = None
            if orderbook.bids and orderbook.asks:
                spread = orderbook.asks[0][0] - orderbook.bids[0][0]
            
            with self.get_connection() as conn:
                conn.execute("""
                    INSERT INTO orderbook_snapshots 
                    (symbol, timestamp, bids, asks, spread)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    symbol,
                    orderbook.timestamp,
                    json.dumps(orderbook.bids[:10]),  # Store top 10 levels
                    json.dumps(orderbook.asks[:10]),
                    spread
                ))
            logger.debug(f"Saved orderbook for {symbol}")
            return True
        except Exception as e:
            logger.error(f"Failed to save orderbook: {e}")
            return False
    
    def get_latest_price(self, symbol: str) -> Optional[float]:
        """Get the latest price for a symbol."""
        with self.get_connection() as conn:
            result = conn.execute("""
                SELECT last FROM prices 
                WHERE symbol = ? 
                ORDER BY timestamp DESC 
                LIMIT 1
            """, (symbol,)).fetchone()
            
            return result['last'] if result else None
    
    def get_recent_candles(self, symbol: str, timeframe: str, limit: int = 100) -> pl.DataFrame:
        """Get recent candles as a Polars DataFrame."""
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT timestamp, open, high, low, close, volume
                FROM candles
                WHERE symbol = ? AND timeframe = ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (symbol, timeframe, limit))
            
            rows = cursor.fetchall()
            
            if not rows:
                return pl.DataFrame()
            
            # Convert to Polars DataFrame
            data = {
                'timestamp': [row['timestamp'] for row in rows],
                'open': [row['open'] for row in rows],
                'high': [row['high'] for row in rows],
                'low': [row['low'] for row in rows],
                'close': [row['close'] for row in rows],
                'volume': [row['volume'] for row in rows],
            }
            
            df = pl.DataFrame(data)
            return df.sort('timestamp')  # Return in chronological order
    
    def get_stats(self) -> Dict[str, Any]:
        """Get database statistics."""
        with self.get_connection() as conn:
            stats = {}
            
            # Count records in each table
            for table in ['prices', 'candles', 'orderbook_snapshots', 'trades']:
                count = conn.execute(f"SELECT COUNT(*) as cnt FROM {table}").fetchone()
                stats[f'{table}_count'] = count['cnt']
            
            # Get date range
            result = conn.execute("""
                SELECT MIN(timestamp) as min_time, MAX(timestamp) as max_time 
                FROM prices
            """).fetchone()
            
            if result['min_time']:
                stats['earliest_data'] = result['min_time']
                stats['latest_data'] = result['max_time']
            
            return stats
    
    # ============= NEW SESSION METHODS =============
    
    def create_session(
        self, 
        name: str,
        description: str = None, # type: ignore
        strategies: List[str] = None, # type: ignore
        parameters: Dict[str, Any] = None, # type: ignore
        is_live: bool = False
    ) -> str:
        """Create a new trading/testing session."""
        session_id = str(uuid.uuid4())[:8]  # Short ID for readability
        
        with self.get_connection() as conn:
            conn.execute("""
                INSERT INTO sessions 
                (session_id, name, description, strategies, parameters, is_live)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                session_id,
                name,
                description,
                json.dumps(strategies or []),
                json.dumps(parameters or {}),
                int(is_live)
            ))
        
        logger.info(f"Created session '{name}' with ID: {session_id}")
        return session_id
    
    def end_session(self, session_id: str):
        """Mark a session as completed and calculate final stats."""
        with self.get_connection() as conn:
            # Calculate session stats
            stats = conn.execute("""
                SELECT 
                    COUNT(*) as trade_count,
                    COALESCE(SUM(pnl), 0) as total_pnl
                FROM trades
                WHERE session_id = ?
            """, (session_id,)).fetchone()
            
            # Update session
            conn.execute("""
                UPDATE sessions 
                SET 
                    ended_at = CURRENT_TIMESTAMP,
                    status = 'completed',
                    total_pnl = ?,
                    trade_count = ?
                WHERE session_id = ?
            """, (stats['total_pnl'], stats['trade_count'], session_id))
        
        logger.info(f"Session {session_id} completed. P&L: ${stats['total_pnl']:.2f}")
    
    def log_trade(
        self, 
        order_id: str, 
        symbol: str, 
        side: str, 
        price: float, 
        amount: float, 
        fee: float = 0, 
        strategy: str = None, # type: ignore
        session_id: str = None,  # NEW: Optional session ID # type: ignore
        is_paper: bool = True     # NEW: Paper trading flag
    ) -> bool:
        """Log a trade execution."""
        try:
            with self.get_connection() as conn:
                conn.execute("""
                    INSERT INTO trades 
                    (session_id, order_id, symbol, side, price, amount, fee, timestamp, strategy, is_paper)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    session_id,
                    order_id,
                    symbol,
                    side,
                    price,
                    amount,
                    fee,
                    datetime.now(),
                    strategy,
                    int(is_paper)
                ))
            
            log_msg = f"Logged trade: {side} {amount} {symbol} @ {price}"
            if session_id:
                log_msg = f"[Session {session_id}] {log_msg}"
            logger.success(log_msg)
            return True
        except Exception as e:
            logger.error(f"Failed to log trade: {e}")
            return False
    
    def log_signal(
        self,
        session_id: str,
        symbol: str,
        signal_type: str,
        strength: float,
        price: float,
        reason: str,
        strategy: str,
        traded: bool = False
    ):
        """Log a signal (whether traded or not)."""
        with self.get_connection() as conn:
            conn.execute("""
                INSERT INTO signals
                (session_id, symbol, signal_type, strength, price, reason, strategy, traded)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                session_id,
                symbol,
                signal_type,
                strength,
                price,
                reason,
                strategy,
                int(traded)
            ))
    
    def get_session_trades(self, session_id: str) -> pl.DataFrame:
        """Get all trades for a specific session."""
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT * FROM trades
                WHERE session_id = ?
                ORDER BY timestamp DESC
            """, (session_id,))
            
            rows = cursor.fetchall()
            if not rows:
                return pl.DataFrame()
            
            # Convert to Polars DataFrame
            data = {key: [row[key] for row in rows] for key in rows[0].keys()}
            return pl.DataFrame(data)
    
    def compare_sessions(self, session_ids: List[str]) -> pl.DataFrame:
        """Compare performance across multiple sessions."""
        with self.get_connection() as conn:
            placeholders = ','.join('?' * len(session_ids))
            cursor = conn.execute(f"""
                SELECT 
                    s.session_id,
                    s.name,
                    s.is_live,
                    s.started_at,
                    s.ended_at,
                    COUNT(t.id) as trade_count,
                    COALESCE(SUM(t.pnl), 0) as total_pnl,
                    COALESCE(AVG(t.pnl), 0) as avg_pnl,
                    SUM(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) as winning_trades,
                    SUM(CASE WHEN t.pnl < 0 THEN 1 ELSE 0 END) as losing_trades
                FROM sessions s
                LEFT JOIN trades t ON s.session_id = t.session_id
                WHERE s.session_id IN ({placeholders})
                GROUP BY s.session_id
            """, session_ids)
            
            rows = cursor.fetchall()
            if not rows:
                return pl.DataFrame()
            
            data = {key: [row[key] for row in rows] for key in rows[0].keys()}
            df = pl.DataFrame(data)
            
            # Add win rate calculation
            df = df.with_columns(
                (pl.col("winning_trades") / pl.col("trade_count")).alias("win_rate")
            )
            
            return df
    
    def get_active_sessions(self) -> List[Dict[str, Any]]:
        """Get all active sessions."""
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT session_id, name, started_at, is_live
                FROM sessions
                WHERE status = 'active'
                ORDER BY started_at DESC
            """)
            
            return [dict(row) for row in cursor.fetchall()]


# Test the database
if __name__ == "__main__":
    db = Database()
    
    # Create a test session
    session_id = db.create_session(
        name="Test Session",
        description="Testing session features",
        strategies=["RatioMeanReversion"],
        parameters={"threshold": 2.0}
    )
    
    # Log a test trade with session
    db.log_trade(
        session_id=session_id,
        order_id="TEST123",
        symbol="BTC/USDT",
        side="buy",
        price=100000,
        amount=0.01,
        strategy="RatioMeanReversion"
    )
    
    # Check stats
    stats = db.get_stats()
    logger.success(f"Database stats: {stats}")
    
    # Check active sessions
    sessions = db.get_active_sessions()
    logger.info(f"Active sessions: {sessions}")