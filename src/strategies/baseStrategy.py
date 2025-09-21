"""Base strategy class for all trading strategies."""

from abc import ABC, abstractmethod
from typing import Optional, List, TYPE_CHECKING
from loguru import logger

if TYPE_CHECKING:
    from ..data.sources.base import DataSource
    from ..trading.models import Signal


class BaseStrategy(ABC):
    def __init__(
        self,
        name: str,
        datasource: "DataSource"
    ):
        self.name = name
        self.datasource = datasource
        self.signals_history: List["Signal"] = []
        self.is_active = True

    @abstractmethod
    async def calculate_signal(self) -> List["Signal"]:
        """Calculate trading signals based on datasource.

        Returns:
            List of signals (empty list if no signals)
        """
        pass

    def get_name(self) -> str:
        """Get strategy name.

        Returns:
            Strategy name
        """
        return self.name