"""Binance exchange client implementation."""

import ccxt
from typing import Dict, List, Optional, Union, Any, Literal, cast
from datetime import datetime
from loguru import logger

from ..base import BaseExchangeClient, Ticker, Candle, OrderBook


class BinanceClient(BaseExchangeClient):
    """Binance US exchange client using CCXT."""
    
    def __init__(self, api_key: Optional[str] = None, secret_key: Optional[str] = None, testnet: bool = False):
        super().__init__(api_key, secret_key)
        
        # Configure exchange
        config: Dict[str, Any] = {}
        
        if api_key and secret_key:
            config['apiKey'] = api_key
            config['secret'] = secret_key
        
        # Use Binance US for US users, regular Binance otherwise
        self.exchange = ccxt.binanceus(config)  # type: ignore[arg-type]
        
        # Set rate limiting after initialization
        self.exchange.enableRateLimit = True
        
        if testnet:
            # Binance testnet URLs
            self.exchange.set_sandbox_mode(True)
        
        logger.info(f"BinanceClient initialized {'(testnet)' if testnet else ''}")
    
    def get_ticker(self, symbol: str) -> Ticker:
        """Get current ticker for a symbol."""
        try:
            ticker_data = self.exchange.fetch_ticker(symbol)
            
            timestamp = ticker_data.get('timestamp')
            if timestamp is None:
                timestamp = datetime.now().timestamp() * 1000
            
            return Ticker(
                symbol=symbol,
                timestamp=datetime.fromtimestamp(float(timestamp) / 1000),
                bid=float(ticker_data['bid']) if ticker_data['bid'] is not None else 0.0,
                ask=float(ticker_data['ask']) if ticker_data['ask'] is not None else 0.0,
                last=float(ticker_data['last']) if ticker_data['last'] is not None else 0.0,
                volume_24h=float(ticker_data['quoteVolume']) if ticker_data['quoteVolume'] is not None else 0.0
            )
        except Exception as e:
            logger.error(f"Error fetching ticker for {symbol}: {e}")
            raise
    
    def get_candles(
        self, 
        symbol: str, 
        timeframe: str = '1h',
        limit: int = 100
    ) -> List[Candle]:
        """
        Get historical OHLCV candles.
        Timeframes: 1m, 5m, 15m, 30m, 1h, 4h, 1d, 1w
        """
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            
            candles = []
            for candle in ohlcv:
                candles.append(Candle(
                    timestamp=datetime.fromtimestamp(candle[0] / 1000),
                    open=candle[1],
                    high=candle[2],
                    low=candle[3],
                    close=candle[4],
                    volume=candle[5]
                ))
            
            logger.debug(f"Fetched {len(candles)} candles for {symbol}")
            return candles
            
        except Exception as e:
            logger.error(f"Error fetching candles for {symbol}: {e}")
            raise
    
    def get_orderbook(self, symbol: str, depth: int = 20) -> OrderBook:
        """Get current order book."""
        try:
            book = self.exchange.fetch_order_book(symbol, limit=depth)
            
            timestamp = book.get('timestamp')
            if timestamp is not None:
                book_timestamp = datetime.fromtimestamp(float(timestamp) / 1000)
            else:
                book_timestamp = datetime.now()
            
            return OrderBook(
                symbol=symbol,
                timestamp=book_timestamp,
                bids=[(float(bid[0]), float(bid[1])) for bid in book['bids'] if bid[0] is not None and bid[1] is not None],
                asks=[(float(ask[0]), float(ask[1])) for ask in book['asks'] if ask[0] is not None and ask[1] is not None]
            )
            
        except Exception as e:
            logger.error(f"Error fetching orderbook for {symbol}: {e}")
            raise
    
    def get_balance(self) -> Dict[str, float]:
        """Get account balances."""
        if not self.api_key or not self.secret_key:
            logger.warning("No API keys provided, cannot fetch balance")
            return {}
        
        try:
            balance = self.exchange.fetch_balance()
            
            # Return only non-zero balances
            non_zero: Dict[str, float] = {}
            for asset, amount in balance['free'].items():
                if amount is not None:
                    try:
                        float_amount = float(amount)  # type: ignore[arg-type]
                        if float_amount > 0:
                            non_zero[asset] = float_amount
                    except (ValueError, TypeError):
                        continue
            
            logger.debug(f"Fetched balances: {non_zero}")
            return non_zero
            
        except Exception as e:
            logger.error(f"Error fetching balance: {e}")
            raise
    
    def place_order(
        self,
        symbol: str,
        side: str,  # "buy" or "sell"
        amount: float,
        price: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Place an order.
        If price is None, places a market order.
        """
        if not self.api_key or not self.secret_key:
            logger.error("No API keys provided, cannot place orders")
            raise ValueError("API keys required for trading")
        
        try:
            order_type = 'limit' if price else 'market'
            
            if order_type == 'limit':
                order = self.exchange.create_order(
                    symbol=symbol,
                    type=order_type,
                    side=side,  # type: ignore[arg-type]
                    amount=amount,
                    price=price
                )
            else:
                order = self.exchange.create_order(
                    symbol=symbol,
                    type=order_type,
                    side=side,  # type: ignore[arg-type]
                    amount=amount
                )
            
            logger.success(f"Placed {side} order for {amount} {symbol} at {price or 'market'}")
            return dict(order)
            
        except Exception as e:
            logger.error(f"Error placing order: {e}")
            raise
    
    def cancel_order(self, order_id: str, symbol: str) -> bool:
        """Cancel an order."""
        if not self.api_key or not self.secret_key:
            logger.error("No API keys provided, cannot cancel orders")
            return False
        
        try:
            self.exchange.cancel_order(order_id, symbol)
            logger.success(f"Cancelled order {order_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error cancelling order {order_id}: {e}")
            return False
    
    def get_exchange_info(self) -> dict:
        """Get exchange trading rules and symbol info."""
        try:
            return self.exchange.load_markets()
        except Exception as e:
            logger.error(f"Error loading markets: {e}")
            raise


# Quick test
if __name__ == "__main__":
    client = BinanceClient()
    
    # Test public endpoints (no API key needed)
    ticker = client.get_ticker("BTC/USDT")
    print(f"BTC Price: ${ticker.last:,.2f}")
    print(f"Bid: ${ticker.bid:,.2f} | Ask: ${ticker.ask:,.2f}")
    
    # Get some candles
    candles = client.get_candles("ETH/USDT", "1h", limit=5)
    print(f"\nLast 5 hourly candles for ETH:")
    for candle in candles:
        print(f"  {candle.timestamp}: Close ${candle.close:,.2f}")