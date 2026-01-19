"""
Enhanced Option Chain Fetcher

Provides advanced option chain fetching and filtering capabilities with:
- Delta-based strike selection
- Liquidity filtering (OI, volume, spreads)
- Multiple expiration date support
- 0DTE detection
- Comprehensive caching
"""

import logging
from dataclasses import dataclass
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Tuple
from enum import Enum

from alpaca.data.historical.option import OptionHistoricalDataClient
from alpaca.data.requests import OptionChainRequest
from alpaca.data.models.snapshots import OptionsSnapshot

logger = logging.getLogger(__name__)


class OptionType(Enum):
    """Option contract type."""
    CALL = "C"
    PUT = "P"
    BOTH = "BOTH"


@dataclass
class StrikeFilter:
    """Filtering criteria for option strikes."""

    # Delta filters
    delta_min: Optional[float] = None
    delta_max: Optional[float] = None
    target_delta: Optional[float] = None  # If set, will find closest to this delta

    # Moneyness filters
    min_strike: Optional[float] = None
    max_strike: Optional[float] = None
    strike_count: Optional[int] = None  # Number of strikes around ATM

    # Liquidity filters
    min_open_interest: int = 0
    min_volume: int = 0
    max_bid_ask_spread_pct: float = 1.0  # 100% max spread
    min_bid_price: float = 0.01  # Avoid penny options

    # Greeks filters
    min_implied_volatility: Optional[float] = None
    max_implied_volatility: Optional[float] = None

    # Option type
    option_type: OptionType = OptionType.BOTH


@dataclass
class SelectedContract:
    """A selected option contract with scoring information."""

    symbol: str
    snapshot: OptionsSnapshot
    score: float

    # Parsed contract details
    underlying: str
    strike: float
    expiration: date
    option_type: str  # "call" or "put"

    # Key metrics
    delta: Optional[float] = None
    gamma: Optional[float] = None
    theta: Optional[float] = None
    vega: Optional[float] = None
    implied_volatility: Optional[float] = None
    open_interest: Optional[int] = None
    bid: Optional[float] = None
    ask: Optional[float] = None
    mid: Optional[float] = None
    last_price: Optional[float] = None
    bid_ask_spread_pct: Optional[float] = None

    def __post_init__(self):
        """Extract metrics from snapshot."""
        if self.snapshot.greeks:
            self.delta = self.snapshot.greeks.delta
            self.gamma = self.snapshot.greeks.gamma
            self.theta = self.snapshot.greeks.theta
            self.vega = self.snapshot.greeks.vega

        self.implied_volatility = self.snapshot.implied_volatility
        self.open_interest = self.snapshot.open_interest

        if self.snapshot.latest_quote:
            self.bid = self.snapshot.latest_quote.bid_price
            self.ask = self.snapshot.latest_quote.ask_price
            if self.bid and self.ask:
                self.mid = (self.bid + self.ask) / 2
                if self.ask > 0:
                    self.bid_ask_spread_pct = (self.ask - self.bid) / self.ask

        if self.snapshot.latest_trade:
            self.last_price = self.snapshot.latest_trade.price

    def to_dict(self) -> dict:
        """Convert to dictionary for API responses."""
        return {
            "symbol": self.symbol,
            "underlying": self.underlying,
            "strike": self.strike,
            "expiration": self.expiration.isoformat(),
            "option_type": self.option_type,
            "delta": self.delta,
            "gamma": self.gamma,
            "theta": self.theta,
            "vega": self.vega,
            "implied_volatility": self.implied_volatility,
            "open_interest": self.open_interest,
            "bid": self.bid,
            "ask": self.ask,
            "mid": self.mid,
            "last_price": self.last_price,
            "bid_ask_spread_pct": self.bid_ask_spread_pct,
            "score": self.score,
        }


class OptionChainFetcher:
    """
    Advanced option chain fetcher with filtering and selection logic.

    Example usage:
        fetcher = OptionChainFetcher(api_key, secret_key)

        # Simple delta-based selection
        contract = fetcher.select_best_contract(
            underlying="SPY",
            delta_min=0.60,
            delta_max=0.85,
            min_open_interest=3000
        )

        # Advanced filtering
        filter_criteria = StrikeFilter(
            delta_min=0.45,
            delta_max=0.55,
            min_open_interest=5000,
            max_bid_ask_spread_pct=0.10,
            option_type=OptionType.CALL
        )
        contracts = fetcher.get_filtered_chain(
            underlying="AAPL",
            expiration_date=date.today(),
            strike_filter=filter_criteria
        )
    """

    def __init__(
        self,
        api_key: str,
        secret_key: str,
        cache_ttl_seconds: int = 300
    ):
        """
        Initialize the option chain fetcher.

        Args:
            api_key: Alpaca API key
            secret_key: Alpaca secret key
            cache_ttl_seconds: Cache TTL in seconds (default 5 minutes)
        """
        self.client = OptionHistoricalDataClient(
            api_key=api_key,
            secret_key=secret_key
        )

        self.cache_ttl_seconds = cache_ttl_seconds
        self._chain_cache: Dict[str, Tuple[datetime, Dict[str, OptionsSnapshot]]] = {}
        self._contract_cache: Dict[str, Tuple[datetime, SelectedContract]] = {}

    def get_chain(
        self,
        underlying: str,
        expiration_date: Optional[date] = None,
        use_cache: bool = True
    ) -> Dict[str, OptionsSnapshot]:
        """
        Fetch option chain for an underlying symbol.

        Args:
            underlying: Underlying symbol (e.g., "SPY")
            expiration_date: Optional specific expiration date
            use_cache: Whether to use cached data

        Returns:
            Dictionary of contract symbol -> OptionsSnapshot
        """
        cache_key = f"{underlying}_{expiration_date or 'all'}"

        # Check cache
        if use_cache and cache_key in self._chain_cache:
            cached_time, cached_chain = self._chain_cache[cache_key]
            age = (datetime.utcnow() - cached_time).total_seconds()
            if age < self.cache_ttl_seconds:
                logger.debug(f"Using cached chain for {underlying}")
                return cached_chain

        # Fetch fresh data
        try:
            request_params = {"underlying_symbol": underlying}
            if expiration_date:
                request_params["expiration_date"] = expiration_date.strftime("%Y-%m-%d")

            request = OptionChainRequest(**request_params)
            chain = self.client.get_option_chain(request)

            # Cache it
            self._chain_cache[cache_key] = (datetime.utcnow(), chain)

            logger.info(f"Fetched option chain for {underlying}: {len(chain)} contracts")
            return chain

        except Exception as e:
            logger.error(f"Error fetching option chain for {underlying}: {e}")
            return {}

    def get_filtered_chain(
        self,
        underlying: str,
        expiration_date: Optional[date] = None,
        strike_filter: Optional[StrikeFilter] = None,
        use_cache: bool = True
    ) -> List[SelectedContract]:
        """
        Get filtered option chain based on criteria.

        Args:
            underlying: Underlying symbol
            expiration_date: Optional expiration date filter
            strike_filter: Filtering criteria
            use_cache: Whether to use cached data

        Returns:
            List of SelectedContract objects that pass all filters
        """
        chain = self.get_chain(underlying, expiration_date, use_cache)

        if not chain:
            return []

        if strike_filter is None:
            strike_filter = StrikeFilter()

        filtered_contracts = []

        for contract_symbol, snapshot in chain.items():
            # Parse symbol
            parsed = self._parse_option_symbol(contract_symbol)
            if not parsed:
                continue

            # Apply filters
            if not self._passes_filters(snapshot, parsed, strike_filter):
                continue

            # Calculate score
            score = self._calculate_score(snapshot, parsed, strike_filter)

            contract = SelectedContract(
                symbol=contract_symbol,
                snapshot=snapshot,
                score=score,
                underlying=parsed["underlying"],
                strike=parsed["strike"],
                expiration=parsed["expiration"],
                option_type=parsed["option_type"]
            )

            filtered_contracts.append(contract)

        # Sort by score (highest first)
        filtered_contracts.sort(key=lambda x: x.score, reverse=True)

        logger.info(
            f"Filtered {len(filtered_contracts)} contracts from "
            f"{len(chain)} total for {underlying}"
        )

        return filtered_contracts

    def select_best_contract(
        self,
        underlying: str,
        expiration_date: Optional[date] = None,
        delta_min: float = 0.50,
        delta_max: float = 0.85,
        min_open_interest: int = 1000,
        max_bid_ask_spread_pct: float = 0.30,
        option_type: OptionType = OptionType.CALL,
        use_cache: bool = True
    ) -> Optional[SelectedContract]:
        """
        Select the best option contract based on simple criteria.

        This is a convenience method that wraps get_filtered_chain with
        common parameters for strategy execution.

        Args:
            underlying: Underlying symbol
            expiration_date: Optional expiration date (None = any)
            delta_min: Minimum delta
            delta_max: Maximum delta
            min_open_interest: Minimum open interest
            max_bid_ask_spread_pct: Maximum bid-ask spread percentage
            option_type: CALL, PUT, or BOTH
            use_cache: Whether to use cached data

        Returns:
            Best contract or None if no suitable contract found
        """
        cache_key = (
            f"{underlying}_{expiration_date}_{delta_min}_{delta_max}_"
            f"{min_open_interest}_{max_bid_ask_spread_pct}_{option_type.value}"
        )

        # Check cache
        if use_cache and cache_key in self._contract_cache:
            cached_time, cached_contract = self._contract_cache[cache_key]
            age = (datetime.utcnow() - cached_time).total_seconds()
            if age < self.cache_ttl_seconds:
                logger.debug(f"Using cached contract selection for {underlying}")
                return cached_contract

        # Build filter
        strike_filter = StrikeFilter(
            delta_min=delta_min,
            delta_max=delta_max,
            min_open_interest=min_open_interest,
            max_bid_ask_spread_pct=max_bid_ask_spread_pct,
            option_type=option_type,
            target_delta=(delta_min + delta_max) / 2  # Target the middle
        )

        # Get filtered contracts
        contracts = self.get_filtered_chain(
            underlying=underlying,
            expiration_date=expiration_date,
            strike_filter=strike_filter,
            use_cache=use_cache
        )

        if not contracts:
            logger.warning(f"No suitable contracts found for {underlying}")
            return None

        # Return best (highest score)
        best_contract = contracts[0]

        # Cache it
        self._contract_cache[cache_key] = (datetime.utcnow(), best_contract)

        logger.info(
            f"Selected best contract for {underlying}: {best_contract.symbol} "
            f"(score: {best_contract.score:.2f}, delta: {best_contract.delta:.3f})"
        )

        return best_contract

    def get_0dte_contracts(
        self,
        underlying: str,
        delta_min: float = 0.60,
        delta_max: float = 0.85,
        min_open_interest: int = 3000
    ) -> List[SelectedContract]:
        """
        Get 0DTE (same-day expiration) option contracts.

        Args:
            underlying: Underlying symbol
            delta_min: Minimum delta
            delta_max: Maximum delta
            min_open_interest: Minimum open interest

        Returns:
            List of 0DTE contracts sorted by score
        """
        today = date.today()

        contracts = self.get_filtered_chain(
            underlying=underlying,
            expiration_date=today,
            strike_filter=StrikeFilter(
                delta_min=delta_min,
                delta_max=delta_max,
                min_open_interest=min_open_interest,
                option_type=OptionType.CALL
            )
        )

        logger.info(f"Found {len(contracts)} 0DTE contracts for {underlying}")
        return contracts

    def _passes_filters(
        self,
        snapshot: OptionsSnapshot,
        parsed: dict,
        strike_filter: StrikeFilter
    ) -> bool:
        """Check if a contract passes all filters."""

        # Option type filter
        if strike_filter.option_type != OptionType.BOTH:
            if parsed["option_type"] == "call" and strike_filter.option_type != OptionType.CALL:
                return False
            if parsed["option_type"] == "put" and strike_filter.option_type != OptionType.PUT:
                return False

        # Greeks must be available for delta filtering
        if not snapshot.greeks:
            return False

        delta = abs(float(snapshot.greeks.delta or 0))

        # Delta filters
        if strike_filter.delta_min is not None and delta < strike_filter.delta_min:
            return False
        if strike_filter.delta_max is not None and delta > strike_filter.delta_max:
            return False

        # Strike filters
        if strike_filter.min_strike is not None and parsed["strike"] < strike_filter.min_strike:
            return False
        if strike_filter.max_strike is not None and parsed["strike"] > strike_filter.max_strike:
            return False

        # Open interest filter
        oi = int(snapshot.open_interest or 0)
        if oi < strike_filter.min_open_interest:
            return False

        # Bid-ask spread filter
        if snapshot.latest_quote:
            bid = float(snapshot.latest_quote.bid_price or 0)
            ask = float(snapshot.latest_quote.ask_price or 0)

            if bid < strike_filter.min_bid_price:
                return False

            if ask > 0:
                spread_pct = (ask - bid) / ask
                if spread_pct > strike_filter.max_bid_ask_spread_pct:
                    return False

        # IV filters
        if snapshot.implied_volatility:
            iv = snapshot.implied_volatility
            if strike_filter.min_implied_volatility and iv < strike_filter.min_implied_volatility:
                return False
            if strike_filter.max_implied_volatility and iv > strike_filter.max_implied_volatility:
                return False

        return True

    def _calculate_score(
        self,
        snapshot: OptionsSnapshot,
        parsed: dict,
        strike_filter: StrikeFilter
    ) -> float:
        """
        Calculate a score for contract selection.

        Scoring factors:
        1. Distance from target delta (if specified)
        2. Open interest (higher is better)
        3. Bid-ask spread (tighter is better)
        4. IV (closer to reasonable range is better)
        """
        score = 0.0

        if not snapshot.greeks:
            return score

        delta = abs(float(snapshot.greeks.delta or 0))

        # Delta scoring (0-1 points)
        if strike_filter.target_delta:
            delta_distance = abs(delta - strike_filter.target_delta)
            score += 1.0 - min(delta_distance / 0.5, 1.0)  # Normalize
        else:
            # If no target, prefer middle of range
            if strike_filter.delta_min and strike_filter.delta_max:
                target = (strike_filter.delta_min + strike_filter.delta_max) / 2
                delta_distance = abs(delta - target)
                score += 1.0 - min(delta_distance / 0.5, 1.0)

        # Open interest scoring (0-0.5 points)
        oi = int(snapshot.open_interest or 0)
        score += min(oi / 100000, 0.5)  # Max bonus at 100k OI

        # Spread scoring (0-0.3 points)
        if snapshot.latest_quote:
            bid = float(snapshot.latest_quote.bid_price or 0)
            ask = float(snapshot.latest_quote.ask_price or 0)
            if ask > 0:
                spread_pct = (ask - bid) / ask
                # Reward tight spreads
                score += max(0.3 - spread_pct, 0)

        # IV scoring (0-0.2 points)
        if snapshot.implied_volatility:
            iv = snapshot.implied_volatility
            # Reward reasonable IV (0.2 - 0.8 is good)
            if 0.2 <= iv <= 0.8:
                score += 0.2
            elif 0.1 <= iv <= 1.0:
                score += 0.1

        return score

    @staticmethod
    def _parse_option_symbol(symbol: str) -> Optional[dict]:
        """
        Parse OCC option symbol format.

        Format: TICKER[variable]YYMMDD[C/P]STRIKE[8]
        Example: SPY250117C00590000 -> SPY, 2025-01-17, Call, 590.00

        Returns:
            dict with keys: 'underlying', 'strike', 'expiration', 'option_type'
        """
        try:
            # Find where C or P is (call/put indicator)
            cp_index = -1
            for i, char in enumerate(symbol):
                if char in ("C", "P"):
                    # Verify format: 6 digits before, 8 after
                    if i >= 6 and len(symbol) - i == 9:
                        cp_index = i
                        break

            if cp_index == -1:
                return None

            # Extract parts
            underlying = symbol[:cp_index - 6]
            exp_str = symbol[cp_index - 6:cp_index]
            option_type = "call" if symbol[cp_index] == "C" else "put"
            strike_str = symbol[cp_index + 1:cp_index + 9]

            # Parse expiration
            year = 2000 + int(exp_str[:2])
            month = int(exp_str[2:4])
            day = int(exp_str[4:6])
            expiration = date(year, month, day)

            # Parse strike
            strike = float(strike_str) / 1000

            return {
                "underlying": underlying,
                "strike": strike,
                "expiration": expiration,
                "option_type": option_type
            }
        except (ValueError, IndexError):
            return None

    def clear_cache(self):
        """Clear all caches."""
        self._chain_cache.clear()
        self._contract_cache.clear()
        logger.info("Cleared option chain cache")
