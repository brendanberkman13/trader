"""BTC/ETH Ratio Mean Reversion Strategy.

This strategy works with both live and backtest data sources.
"""

from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime
from enum import Enum
from loguru import logger
import numpy as np

from .baseStrategy import BaseStrategy
from ..trading.models import Signal, SignalType
from ..data.sources.base import DataSource


class PairState(Enum):
    """State of the pairs trade."""
    NEUTRAL = "neutral"
    LONG_B_SHORT_A = "long_b_short_a"  # When symbol_a is expensive (high z-score)
    LONG_A_SHORT_B = "long_a_short_b"  # When symbol_b is expensive (low z-score)


class RatioStrategy(BaseStrategy):
    """Ratio strategy that works with any DataSource."""

    def __init__(
        self,
        datasource: DataSource,
        symbol_a: str = "BTC/USDT",
        symbol_b: str = "ETH/USDT",
        lookback_periods: int = 20,
        entry_threshold: float = 2.0,
        exit_threshold: float = 0.5
    ):
        super().__init__(
            name=f"{symbol_a.split('/')[0]}/{symbol_b.split('/')[0]} Ratio Mean Reversion",
            datasource=datasource
        )
        self.symbol_a = symbol_a  # Numerator of ratio
        self.symbol_b = symbol_b  # Denominator of ratio
        self.lookback_periods = lookback_periods
        self.entry_threshold = entry_threshold
        self.exit_threshold = exit_threshold

        # Track current statistics
        self.current_ratio = 0.0
        self.ratio_mean = 0.0
        self.ratio_std = 0.0
        self.z_score = 0.0

        # State machine for pairs trading
        self.state = PairState.NEUTRAL

    async def get_current_prices(self) -> Tuple[Optional[float], Optional[float]]:
        """Get current prices for symbol_a and symbol_b from datasource."""
        symbol_a_data = await self.datasource.get_current_price(self.symbol_a)
        symbol_b_data = await self.datasource.get_current_price(self.symbol_b)

        symbol_a_price = symbol_a_data.price if symbol_a_data else None
        symbol_b_price = symbol_b_data.price if symbol_b_data else None

        return symbol_a_price, symbol_b_price

    async def get_ratio_history(self) -> List[float]:
        """Get historical ratios from datasource."""
        try:
            # Get price ratio history using datasource method
            ratio_data = await self.datasource.get_price_ratio_history(
                self.symbol_a,
                self.symbol_b,
                limit=self.lookback_periods * 2  # Get extra for safety
            )

            if not ratio_data:
                logger.debug(f"No ratio history available for {self.symbol_a}/{self.symbol_b}")
                return []

            # Extract just the ratio values
            ratios = [ratio for timestamp, ratio in ratio_data]

            return ratios[-self.lookback_periods:] if ratios else []

        except Exception as e:
            logger.error(f"Error getting ratio history: {e}")
            return []

    def calculate_z_score(self, current_ratio: float, historical_ratios: List[float]) -> float:
        """Calculate z-score from ratio data.

        Args:
            current_ratio: Current symbol_a/symbol_b ratio
            historical_ratios: List of historical ratios

        Returns:
            Z-score of current ratio
        """
        if len(historical_ratios) < self.lookback_periods:
            return 0.0

        recent_ratios = historical_ratios[-self.lookback_periods:]
        mean = np.mean(recent_ratios)
        std = np.std(recent_ratios)

        if std == 0:
            return 0.0

        z_score = (current_ratio - mean) / std

        # Update internal state
        self.current_ratio = current_ratio
        self.ratio_mean = mean
        self.ratio_std = std
        self.z_score = z_score

        return z_score # type: ignore

    def generate_entry_signals(
        self,
        z_score: float,
        symbol_a_price: float,
        symbol_b_price: float
    ) -> List[Signal]:
        """Generate entry signals when transitioning from NEUTRAL state.

        Args:
            z_score: Current z-score
            symbol_a_price: Current symbol_a price
            symbol_b_price: Current symbol_b price

        Returns:
            List of entry signals (always 2 for pairs trade)
        """
        signals = []
        strength = min(abs(z_score) / 3, 1.0)

        # High Z-score: symbol_a expensive relative to symbol_b
        # → Buy symbol_b (undervalued) and Sell symbol_a (overvalued)
        if z_score > self.entry_threshold:
            signals.append(Signal(
                symbol=self.symbol_b,
                signal=SignalType.BUY,
                strength=strength,
                price=symbol_b_price,
                reason=f"Pairs entry: Z-score {z_score:.2f} > {self.entry_threshold} ({self.symbol_b} undervalued)"
            ))
            signals.append(Signal(
                symbol=self.symbol_a,
                signal=SignalType.SELL,
                strength=strength,
                price=symbol_a_price,
                reason=f"Pairs entry: Z-score {z_score:.2f} > {self.entry_threshold} ({self.symbol_a} overvalued)"
            ))
            self.state = PairState.LONG_B_SHORT_A

        # Low Z-score: symbol_a cheap relative to symbol_b
        # → Buy symbol_a (undervalued) and Sell symbol_b (overvalued)
        elif z_score < -self.entry_threshold:
            signals.append(Signal(
                symbol=self.symbol_a,
                signal=SignalType.BUY,
                strength=strength,
                price=symbol_a_price,
                reason=f"Pairs entry: Z-score {z_score:.2f} < -{self.entry_threshold} ({self.symbol_a} undervalued)"
            ))
            signals.append(Signal(
                symbol=self.symbol_b,
                signal=SignalType.SELL,
                strength=strength,
                price=symbol_b_price,
                reason=f"Pairs entry: Z-score {z_score:.2f} < -{self.entry_threshold} ({self.symbol_b} overvalued)"
            ))
            self.state = PairState.LONG_A_SHORT_B

        return signals

    def generate_exit_signals(
        self,
        z_score: float,
        symbol_a_price: float,
        symbol_b_price: float
    ) -> List[Signal]:
        """Generate exit signals when z-score normalizes.

        Args:
            z_score: Current z-score
            symbol_a_price: Current symbol_a price
            symbol_b_price: Current symbol_b price

        Returns:
            List of exit signals (always 2 for pairs trade)
        """
        signals = []

        # Only exit if z-score has normalized
        if abs(z_score) < self.exit_threshold:
            if self.state == PairState.LONG_B_SHORT_A:
                # We were long symbol_b, short symbol_a - now close both
                signals.append(Signal(
                    symbol=self.symbol_b,
                    signal=SignalType.SELL,
                    strength=0.8,
                    price=symbol_b_price,
                    reason=f"Pairs exit: Z-score normalized to {z_score:.2f}"
                ))
                signals.append(Signal(
                    symbol=self.symbol_a,
                    signal=SignalType.BUY,
                    strength=0.8,
                    price=symbol_a_price,
                    reason=f"Pairs exit: Z-score normalized to {z_score:.2f}"
                ))
                self.state = PairState.NEUTRAL

            elif self.state == PairState.LONG_A_SHORT_B:
                # We were long symbol_a, short symbol_b - now close both
                signals.append(Signal(
                    symbol=self.symbol_a,
                    signal=SignalType.SELL,
                    strength=0.8,
                    price=symbol_a_price,
                    reason=f"Pairs exit: Z-score normalized to {z_score:.2f}"
                ))
                signals.append(Signal(
                    symbol=self.symbol_b,
                    signal=SignalType.BUY,
                    strength=0.8,
                    price=symbol_b_price,
                    reason=f"Pairs exit: Z-score normalized to {z_score:.2f}"
                ))
                self.state = PairState.NEUTRAL

        return signals

    async def calculate_signal(self) -> List[Signal]:
        """Calculate trading signals using clean state machine flow.

        Flow:
        1. If in position: check if should exit → return exit signals
        2. If neutral: check if should enter → return entry signals
        3. Else: return empty list

        Returns:
            List of signals (empty if no action needed)
        """
        try:
            # Get current prices from datasource
            symbol_a_price, symbol_b_price = await self.get_current_prices()

            if not symbol_a_price or not symbol_b_price:
                logger.debug(f"Missing price data for {self.symbol_a} or {self.symbol_b}")
                return []

            current_ratio = symbol_a_price / symbol_b_price

            # Get historical ratios and calculate z-score
            historical_ratios = await self.get_ratio_history()

            if len(historical_ratios) < self.lookback_periods:
                logger.debug(f"Insufficient history: {len(historical_ratios)}/{self.lookback_periods}")
                return []

            z_score = self.calculate_z_score(current_ratio, historical_ratios)

            # Log current state
            logger.debug(
                f"Pairs Trading [{self.state.value}] - Ratio: {current_ratio:.2f} "
                f"(mean: {self.ratio_mean:.2f}, std: {self.ratio_std:.2f}, z-score: {z_score:.2f})"
            )

            # Clean flow logic:
            # 1. If in position: check exit conditions
            if self.state in [PairState.LONG_B_SHORT_A, PairState.LONG_A_SHORT_B]:
                if abs(z_score) < self.exit_threshold:
                    signals = self.generate_exit_signals(z_score, symbol_a_price, symbol_b_price)
                    if signals:
                        logger.debug(f"Closing pairs trade: {self.state.value} → {PairState.NEUTRAL.value}")
                    return signals

            # 2. If neutral: check entry conditions
            elif self.state == PairState.NEUTRAL:
                if abs(z_score) > self.entry_threshold:
                    signals = self.generate_entry_signals(z_score, symbol_a_price, symbol_b_price)
                    if signals:
                        logger.debug(f"Opening pairs trade: {PairState.NEUTRAL.value} → {self.state.value}")
                    return signals

            # 3. No action needed
            return []

        except Exception as e:
            logger.error(f"Error calculating signal: {e}")
            return []

    def get_stats(self) -> Dict[str, Any]:
        """Get current strategy statistics."""
        return {
            "name": self.name,
            "state": self.state.value,
            "current_ratio": round(self.current_ratio, 2),
            "ratio_mean": round(self.ratio_mean, 2),
            "ratio_std": round(self.ratio_std, 2),
            "z_score": round(self.z_score, 2),
            "entry_threshold": self.entry_threshold,
            "exit_threshold": self.exit_threshold,
            "lookback_periods": self.lookback_periods,
            "datasource_type": type(self.datasource).__name__
        }


# Demo usage
if __name__ == "__main__":
    pass