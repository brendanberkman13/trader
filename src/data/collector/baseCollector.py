"""Base collector class for all data collectors."""

from abc import ABC, abstractmethod
from typing import List, Optional
import asyncio
from loguru import logger
from datetime import datetime


class BaseCollector(ABC):
    """Abstract base class for data collectors."""
    
    def __init__(self, symbols: List[str], interval_seconds: int = 30):
        self.symbols = symbols
        self.interval_seconds = interval_seconds
        self.is_running = False
        self._task: Optional[asyncio.Task] = None
        
    @abstractmethod
    async def collect_once(self):
        """Collect data once for all symbols."""
        pass
    
    async def start(self):
        """Start continuous collection."""
        if self.is_running:
            logger.warning("Collector already running")
            return
            
        self.is_running = True
        logger.info(f"Starting collector for {len(self.symbols)} symbols every {self.interval_seconds}s")
        
        while self.is_running:
            try:
                start_time = asyncio.get_event_loop().time()
                await self.collect_once()
                
                # Calculate how long to sleep to maintain interval
                elapsed = asyncio.get_event_loop().time() - start_time
                sleep_time = max(0, self.interval_seconds - elapsed)
                
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)
                    
            except Exception as e:
                logger.error(f"Collection error: {e}")
                await asyncio.sleep(self.interval_seconds)
    
    async def stop(self):
        """Stop collection."""
        logger.info("Stopping collector...")
        self.is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass