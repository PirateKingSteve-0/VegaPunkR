"""What underlying move must a long 0DTE option make just to break even?

Written 2026-09-14. Prompted by the BRAINSTORM 2026-09-11 finding that the
opening-range breakout moves SPY +3.69 bp in the break's favour while "a 15%
stop on a morning contract needs ~9.7 bp". That comparison is the right shape
but it was estimated from a single contract; this computes it from the option
model for every hour of the session and every delta the gate allows, so a
candidate signal can be accepted or rejected BEFORE it is measured on tape.

Two different budgets come out, and conflating them is what made the earlier
number hard to act on:

  BREAKEVEN ROOM  the favourable move needed to cover the round-trip spread
                  plus time decay over the hold. Below this the trade loses
                  even when the direction call is right.

  STOP ROOM       the ADVERSE move that fires the percentage stop. This is the
                  number that decides whether the stop is measuring the signal
                  being wrong or just measuring noise.

Both are solved from Black-Scholes by bisection rather than from a linear delta
approximation, because 0DTE gamma over a 30-minute hold is not small.

Calibration: SPY 2026-09-02, strike 760, filled 3.27 at 10:00 ET with the
delta gate requiring >= 0.60 (docs/live-test-results-2026-09-02.md section 2).
IV near 35% annualised reproduces that premium. Conclusions are not sensitive
to +/-20% on IV; they are very sensitive to delta and to time of day.

No network, no DB, stdlib only.
"""
import argparse
import math

MINUTES_PER_YEAR = 365 * 24 * 60
CLOSE_MIN = 16 * 60          # 16:00 ET in minutes past midnight
OPEN_MIN = 9 * 60 + 30       # 09:30 ET
SESSION_MINUTES = CLOSE_MIN - OPEN_MIN   # 390


def _ncdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_call(S, K, minutes_left, iv):
    """Black-Scholes call. r=0: on a 0DTE the carry term is noise."""
    if minutes_left <= 0:
        return max(0.0, S - K)
    T = minutes_left / MINUTES_PER_YEAR
    vol = iv * math.sqrt(T)
    if vol <= 0:
        return max(0.0, S - K)
    d1 = (math.log(S / K) + 0.5 * vol * vol) / vol
    return S * _ncdf(d1) - K * _ncdf(d1 - vol)


def bs_delta(S, K, minutes_left, iv):
    if minutes_left <= 0:
        return 1.0 if S > K else 0.0
    T = minutes_left / MINUTES_PER_YEAR
    vol = iv * math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * vol * vol) / vol
    return _ncdf(d1)


def strike_for_delta(S, minutes_left, iv, target_delta):
    """Bisect on strike. Deeper ITM (lower strike) => higher delta."""
    lo, hi = S * 0.90, S * 1.05
    for _ in range(200):
        mid = (lo + hi) / 2
        if bs_delta(S, mid, minutes_left, iv) > target_delta:
            lo = mid          # too much delta, raise the strike
        else:
            hi = mid
    return round((lo + hi) / 2)          # SPY strikes are $1 wide


def spot_for_premium(K, minutes_left, iv, target_premium):
    """The underlying price at which the contract is worth target_premium."""
    lo, hi = K * 0.80, K * 1.30
    for _ in range(300):
        mid = (lo + hi) / 2
        if bs_call(mid, K, minutes_left, iv) < target_premium:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def sigma_bp(minutes, iv):
    """1-sigma underlying move over `minutes`, in basis points."""
    return iv * math.sqrt(minutes / MINUTES_PER_YEAR) * 10_000


def touch_prob(barrier_sigmas):
    """P(a driftless random walk touches +/-k sigma at some point in the horizon).

    Exact two-barrier survival series (Feller):
        P(max|W| <= a) = sum_k (-1)^k [ N((2k+1)a) - N((2k-1)a) ]
    A one-sided 2*(1-N(a)) understates it; the naive 4*(1-N(a)) overstates it
    and saturates at 1 for anything under ~0.5 sigma, which is exactly the
    range that matters here.
    """
    a = barrier_sigmas
    if a <= 0:
        return 1.0
    survive = 0.0
    for k in range(-60, 61):
        survive += (-1) ** k * (_ncdf((2 * k + 1) * a) - _ncdf((2 * k - 1) * a))
    return max(0.0, min(1.0, 1.0 - survive))


def row(entry_min, spot, iv, target_delta, hold, sl_pct, tp_pct, friction_pct):
    left_in = CLOSE_MIN - entry_min
    left_out = max(0.0, left_in - hold)

    K = strike_for_delta(spot, left_in, iv, target_delta)
    p0 = bs_call(spot, K, left_in, iv)
    delta0 = bs_delta(spot, K, left_in, iv)
    intrinsic = max(0.0, spot - K)
    extrinsic = p0 - intrinsic

    # Decay alone: same spot, `hold` minutes later.
    p_decayed = bs_call(spot, K, left_out, iv)
    theta_pct = (p0 - p_decayed) / p0 * 100.0

    # Favourable move needed to come out flat after spread + decay.
    be_spot = spot_for_premium(K, left_out, iv, p0 * (1 + friction_pct / 100.0))
    be = (be_spot - spot) / spot * 10_000

    # Adverse move that fires the stop, and favourable move that hits target.
    sl_spot = spot_for_premium(K, left_out, iv, p0 * (1 - sl_pct / 100.0))
    tp_spot = spot_for_premium(K, left_out, iv, p0 * (1 + tp_pct / 100.0))
    stop_room = (spot - sl_spot) / spot * 10_000
    tp_room = (tp_spot - spot) / spot * 10_000

    sig = sigma_bp(hold, iv)
    return dict(K=K, p0=p0, delta=delta0, extrinsic=extrinsic,
                theta_pct=theta_pct, be=be, stop_room=stop_room,
                tp_room=tp_room, sigma=sig,
                stop_sigmas=stop_room / sig if sig else 0.0,
                p_touch=touch_prob(stop_room / sig if sig else 0.0))


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--spot", type=float, default=760.0)
    p.add_argument("--iv", type=float, default=0.35,
                   help="annualised, calendar. 0.35 reproduces the 09-02 fill")
    p.add_argument("--hold", type=float, default=30.0,
                   help="minutes; template max_hold_time_minutes is 30")
    p.add_argument("--stop", type=float, default=15.0, help="stop %% of premium")
    p.add_argument("--target", type=float, default=30.0, help="target %% of premium")
    p.add_argument("--friction", type=float, default=2.5,
                   help="round-trip spread+slippage as %% of premium "
                        "(0.5%% entry drift measured 09-02, ~2%% on the market-order exit)")
    p.add_argument("--edge", type=float, default=3.69,
                   help="measured signal edge in bp (ORB, BRAINSTORM 2026-09-11)")
    p.add_argument("--deltas", default="0.60,0.70,0.85",
                   help="template gate is delta_min 0.60 / delta_max 0.85")
    p.add_argument("--times", default="10:00,11:00,13:00,14:00,15:00,15:30")
    a = p.parse_args()

    deltas = [float(x) for x in a.deltas.split(",")]
    times = []
    for t in a.times.split(","):
        h, m = t.split(":")
        times.append((t, int(h) * 60 + int(m)))

    print(f"SPY {a.spot:.0f}   IV {a.iv:.0%}   hold {a.hold:.0f}m   "
          f"SL {a.stop:.0f}% / TP {a.target:.0f}%   friction {a.friction:.1f}% of premium")
    print(f"measured signal edge: {a.edge:.2f} bp\n")

    for d in deltas:
        print(f"--- target delta {d:.2f} " + "-" * 58)
        print(f"{'ET':>6} {'strike':>7} {'prem':>6} {'extr':>6} {'decay':>7} "
              f"{'B/E':>7} {'stop':>7} {'targ':>7} {'1sig':>7} {'stop':>6} {'P(stop':>7}")
        print(f"{'':>6} {'':>7} {'':>6} {'':>6} {'%prem':>7} "
              f"{'bp':>7} {'bp':>7} {'bp':>7} {'bp':>7} {'sigma':>6} {'noise)':>7}")
        for label, em in times:
            r = row(em, a.spot, a.iv, d, a.hold, a.stop, a.target, a.friction)
            print(f"{label:>6} {r['K']:>7d} {r['p0']:>6.2f} {r['extrinsic']:>6.2f} "
                  f"{r['theta_pct']:>7.1f} {r['be']:>7.2f} {r['stop_room']:>7.2f} "
                  f"{r['tp_room']:>7.2f} {r['sigma']:>7.1f} {r['stop_sigmas']:>6.2f} "
                  f"{r['p_touch']:>6.0%}")
        print()

    # The one-line verdict, at the hour the strategy actually trades most.
    print("=" * 78)
    r10 = row(10 * 60, a.spot, a.iv, 0.70, a.hold, a.stop, a.target, a.friction)
    print(f"At 10:00 ET, delta 0.70, {a.hold:.0f}m hold:")
    print(f"  need {r10['be']:.2f} bp to break even; signal supplies {a.edge:.2f} bp "
          f"-> margin {a.edge - r10['be']:+.2f} bp")
    print(f"  stop sits at {r10['stop_sigmas']:.2f} sigma of the move it must survive; "
          f"random walk touches it {r10['p_touch']:.0%} of the time")
    print(f"  edge is {a.edge / r10['sigma']:.3f} sigma. signal-to-noise "
          f"{a.edge / r10['sigma'] / r10['stop_sigmas']:.2f}x the stop distance")


if __name__ == "__main__":
    main()
