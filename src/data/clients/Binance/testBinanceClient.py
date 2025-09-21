"""Test the Binance client implementation."""

from src.data.clients.Binance.binanceClient import BinanceClient
from loguru import logger
import sys

# Configure loguru for better test output
logger.remove()  # Remove default handler
logger.add(sys.stdout, colorize=True, format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")


def test_binance_client():
    """Test all public methods of the Binance client."""
    
    # Initialize client (no API keys needed for public data)
    client = BinanceClient()
    
    logger.info("=" * 50)
    logger.info("TESTING BINANCE CLIENT")
    logger.info("=" * 50)
    
    # Test 1: Get ticker
    logger.info("Testing get_ticker()...")
    try:
        ticker = client.get_ticker("BTC/USDT")
        logger.success(f"BTC/USDT ticker retrieved:")
        logger.info(f"  Price: ${ticker.last:,.2f}")
        logger.info(f"  Bid: ${ticker.bid:,.2f} | Ask: ${ticker.ask:,.2f}")
        logger.info(f"  Spread: ${ticker.ask - ticker.bid:.2f}")
        logger.info(f"  24h Volume: ${ticker.volume_24h:,.0f}")
    except Exception as e:
        logger.error(f"get_ticker failed: {e}")
    
    # Test 2: Get candles
    logger.info("Testing get_candles()...")
    try:
        candles = client.get_candles("ETH/USDT", "1h", limit=5)
        logger.success(f"Retrieved {len(candles)} candles for ETH/USDT")
        for i, candle in enumerate(candles[-3:], 1):  # Show last 3
            logger.debug(f"  Candle {i} @ {candle.timestamp.strftime('%Y-%m-%d %H:%M')}")
            logger.debug(f"    O: ${candle.open:,.2f} H: ${candle.high:,.2f} L: ${candle.low:,.2f} C: ${candle.close:,.2f}")
    except Exception as e:
        logger.error(f"get_candles failed: {e}")
    
    # Test 3: Get orderbook
    logger.info("Testing get_orderbook()...")
    try:
        book = client.get_orderbook("SOL/USDT", depth=5)
        logger.success(f"SOL/USDT order book retrieved")
        
        # Show top bids/asks
        logger.debug("Top 3 Bids:")
        for price, size in book.bids[:3]:
            logger.debug(f"  ${price:,.2f} - Size: {size:.3f}")
        
        logger.debug("Top 3 Asks:")
        for price, size in book.asks[:3]:
            logger.debug(f"  ${price:,.2f} - Size: {size:.3f}")
        
        # Calculate spread
        if book.bids and book.asks:
            spread = book.asks[0][0] - book.bids[0][0]
            spread_pct = (spread / book.bids[0][0]) * 100
            logger.info(f"Spread: ${spread:.2f} ({spread_pct:.3f}%)")
    except Exception as e:
        logger.error(f"get_orderbook failed: {e}")
    
    # Test 4: Get multiple symbols quickly
    logger.info("Testing multiple symbols...")
    symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "MATIC/USDT"]
    try:
        prices = {}
        for symbol in symbols:
            ticker = client.get_ticker(symbol)
            prices[symbol] = ticker.last
            logger.debug(f"  {symbol}: ${ticker.last:,.2f}")
        logger.success(f"Retrieved prices for {len(prices)} symbols")
    except Exception as e:
        logger.error(f"Multiple symbol test failed: {e}")
    
    # Test 5: Test balance (will fail without API keys - expected)
    logger.info("Testing get_balance() without API keys...")
    try:
        balance = client.get_balance()
        if balance:
            logger.warning(f"Unexpected balance returned: {balance}")
        else:
            logger.success("Correctly returned empty dict (no API keys)")
    except Exception as e:
        logger.error(f"get_balance failed unexpectedly: {e}")
    
    logger.info("=" * 50)
    logger.success("TESTING COMPLETE!")
    logger.info("=" * 50)


if __name__ == "__main__":
    test_binance_client()