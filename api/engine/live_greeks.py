"""Delta computed from LIVE prices — because the broker's delta is not live.

Pure math: no network, no DB, no orders. Consumed by the long-shot guard in
SignalGenerator.check_entry_signal (TODO.md G5).

WHY THIS EXISTS
---------------
The engine's delta used to come only from Tradier's option greeks (ORATS). Those
refresh roughly once an hour — the engine re-arms contracts at about :15 past
the hour on almost every recorded day — and at the open they are still the
PREVIOUS EVENING's. Proven 2026-09-17 by recomputing delta from recorded prices:
SPY gapped from ~$754 overnight to $763.16 at the open, the broker kept
reporting 0.727 for the 758 put from 09:30 to 10:08 (twice, from fresh
requests), while its real delta was 0.13-0.27. The engine bought three of them
at $0.49 believing they were in the money.

An audit of all 31 real round trips (2026-09-02..09-17) found 16 bought outside
the 0.60-0.85 band in reality: 5 below it (long shots, three of them bought x3
because they were cheap) and 11 above it (deeper in the money). The owner chose
to guard only the long-shot side for now — the deep side carried nearly all the
profit in that sample and needs study, not a block.

THE CALCULATION
---------------
Black-Scholes with r = 0 (the carry term is noise on a same-day contract).
Implied volatility is solved by bisection from the live option mid, then delta
is read off at that volatility. Solved rather than approximated because 0DTE
gamma is large. Same method as scripts/cost_budget.py and docs/greeks-and-iv.md.

When it cannot be solved:
  * no time value left (price at or below intrinsic) -> a deep in-the-money
    contract; its delta is ~1. Reported as source "no_time_value".
  * no usable quote, or no underlying price -> source "unavailable"; the caller
    falls back to plain moneyness (is the contract in the money right now?).

Time to expiry runs to the market close on the expiry date. SPY options trade a
few minutes past the equity close; ignoring that is immaterial for entries,
which stop at 11:30 ET.
"""
import math
import re
from dataclasses import dataclass
from datetime import date, datetime, time as dtime
from typing import Optional, Tuple

MINUTES_PER_YEAR = 365 * 24 * 60

# An option quote older than this is not used to solve delta. Mirrors
# strategy_executor.MAX_QUOTE_AGE_SECONDS (30s), which the executor applies only
# AFTER the entry check, for sizing — too late for this calculation. Kept as its
# own constant rather than imported: signal_generator -> strategy_executor would
# be a circular import. Change both together.
MAX_QUOTE_AGE_S = 30.0
_OCC = re.compile(r"^[A-Z]{1,6}(\d{2})(\d{2})(\d{2})([CP])(\d{8})$")


def _ncdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def parse_occ(option_symbol: str) -> Optional[Tuple[date, str, float]]:
    """'SPY260917P00758000' -> (2026-09-17, 'P', 758.0), or None."""
    m = _OCC.match((option_symbol or "").strip().upper())
    if not m:
        return None
    yy, mm, dd, kind, strike = m.groups()
    try:
        return date(2000 + int(yy), int(mm), int(dd)), kind, int(strike) / 1000.0
    except ValueError:
        return None


def bs_price_delta(spot: float, strike: float, minutes: float, iv: float,
                   kind: str) -> Tuple[float, float]:
    """(price, delta) for a European call ('C') or put ('P'), r = 0. Delta signed."""
    t = minutes / MINUTES_PER_YEAR
    vol = iv * math.sqrt(t)
    d1 = (math.log(spot / strike) + 0.5 * vol * vol) / vol
    d2 = d1 - vol
    if kind == "C":
        return spot * _ncdf(d1) - strike * _ncdf(d2), _ncdf(d1)
    return strike * _ncdf(-d2) - spot * _ncdf(-d1), _ncdf(d1) - 1.0


def implied_abs_delta(spot: float, strike: float, minutes: float, price: float,
                      kind: str) -> Tuple[Optional[float], Optional[float], str]:
    """(|delta|, implied vol, source). source: computed | no_time_value | unavailable."""
    if not (spot > 0 and strike > 0 and price > 0) or minutes <= 0:
        return None, None, "unavailable"
    intrinsic = max(0.0, spot - strike) if kind == "C" else max(0.0, strike - spot)
    if price <= intrinsic + 0.005:
        return None, None, "no_time_value"
    lo, hi = 0.005, 5.0
    if bs_price_delta(spot, strike, minutes, hi, kind)[0] < price:
        return None, None, "unavailable"          # price above what any sane vol explains
    for _ in range(100):
        mid = (lo + hi) / 2
        if bs_price_delta(spot, strike, minutes, mid, kind)[0] < price:
            lo = mid
        else:
            hi = mid
    iv = (lo + hi) / 2
    return abs(bs_price_delta(spot, strike, minutes, iv, kind)[1]), iv, "computed"


@dataclass
class LiveDelta:
    delta: Optional[float]      # |delta| from live prices; None unless source == "computed"
    iv: Optional[float]
    source: str                 # computed | no_time_value | stale_quote | unavailable
    itm_dollars: Optional[float]   # + in the money, - out of the money; None if unknown
    mid: Optional[float]


def live_delta(option_symbol: str, underlying_price: Optional[float],
               bid: Optional[float], ask: Optional[float],
               now_et: datetime, close_time_et: dtime = dtime(16, 0),
               quote_age_s: Optional[float] = None) -> LiveDelta:
    """Delta for `option_symbol` from the live underlying price and option quote.

    `now_et` may be tz-aware or naive; it is read as ET wall-clock time.
    `close_time_et` is TODAY's close (early-close aware); later expiries use 16:00.
    `quote_age_s`: age of bid/ask. Older than MAX_QUOTE_AGE_S -> "stale_quote",
    because an old option price against a new underlying price solves to a
    wrong volatility and so a wrong delta; the caller falls back to moneyness,
    which needs only the underlying. None means unknown and is not treated as stale.
    """
    parsed = parse_occ(option_symbol)
    if parsed is None:
        return LiveDelta(None, None, "unavailable", None, None)
    expiry, kind, strike = parsed
    spot = float(underlying_price) if underlying_price else None
    itm = None
    if spot and spot > 0:
        itm = (spot - strike) if kind == "C" else (strike - spot)
    if quote_age_s is not None and quote_age_s > MAX_QUOTE_AGE_S:
        return LiveDelta(None, None, "stale_quote", itm, None)
    try:
        b, a = float(bid or 0), float(ask or 0)
    except (TypeError, ValueError):
        b = a = 0.0
    if not (b > 0 and a > 0 and a >= b) or not spot:
        return LiveDelta(None, None, "unavailable", itm, None)
    mid = (b + a) / 2.0
    now = now_et.replace(tzinfo=None) if now_et.tzinfo else now_et
    close = close_time_et if expiry == now.date() else dtime(16, 0)
    minutes = (datetime.combine(expiry, close) - now).total_seconds() / 60.0
    d, iv, source = implied_abs_delta(spot, strike, minutes, mid, kind)
    return LiveDelta(d, iv, source, itm, mid)


# Last broker greeks timestamp seen per contract, for note_greeks_refresh().
_greeks_seen = {}


def note_greeks_refresh(option_symbol: str, updated_at, delta) -> Optional[str]:
    """A log line when the broker's greeks timestamp for this contract is first
    seen or changes, else None. Observation only (TODO.md G5): it records WHEN the
    provider recalculates greeks, instead of inferring an hourly schedule from
    re-arm times. Bounded: one entry per contract, cleared when it grows past 500.
    """
    if not option_symbol or not updated_at:
        return None
    prev = _greeks_seen.get(option_symbol)
    if prev == updated_at:
        return None
    if len(_greeks_seen) > 500:
        _greeks_seen.clear()
    _greeks_seen[option_symbol] = updated_at
    d = f"{abs(float(delta)):.3f}" if delta is not None else "n/a"
    if prev is None:
        return f"Greeks for {option_symbol}: broker updated_at {updated_at} (first seen), delta {d}"
    return f"Greeks REFRESHED for {option_symbol}: broker updated_at {prev} -> {updated_at}, delta {d}"


def is_long_shot(ld: LiveDelta, delta_min: float) -> Tuple[bool, str]:
    """Is this contract really below the delta floor right now? (verdict, why).

    computed      -> real delta below delta_min
    no_time_value -> deep in the money, never a long shot
    stale_quote / unavailable
                  -> fall back to moneyness: out of (or at) the money is a long
                     shot; moneyness unknown too -> treated as a long shot, the
                     most-restrictive answer, because nothing can vouch for it.
    """
    if ld.source == "computed":
        if ld.delta < delta_min:
            return True, f"real delta {ld.delta:.3f} < {delta_min}"
        return False, f"real delta {ld.delta:.3f}"
    if ld.source == "no_time_value":
        return False, "deep in the money (no time value, delta ~1)"
    if ld.itm_dollars is None:
        return True, "real delta and moneyness both unknown"
    if ld.itm_dollars <= 0:
        return True, f"out of the money by ${-ld.itm_dollars:.2f} (delta not computable)"
    return False, f"in the money by ${ld.itm_dollars:.2f} (delta not computable)"
