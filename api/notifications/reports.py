"""
End-of-period trade reports.

Aggregates `Trade` rows by user + period window, renders a self-contained
HTML email (no external CSS), and dispatches via `notifications.email`.
Period windows are anchored to US/Eastern trading days because that's the
session boundary the user thinks in, even though `Trade.exit_timestamp`
is stored in UTC.

Period semantics:
- daily      = today's ET session
- weekly     = the ISO week containing today (Mon → today)
- monthly    = MTD (1st of this month → today)
- quarterly  = QTD (Jan/Apr/Jul/Oct 1st → today)
- yearly     = YTD (Jan 1 → today)

Period firing rule (decided by the dispatcher, not this module):
- daily fires every trading day; weekly on the week's last trading day,
  monthly on the month's last trading day, etc. Daily/weekly skip when
  the period closed zero trades; monthly+ always send (we want the
  record even on a flat month).
"""
import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Dict, List, Optional, Tuple

import pytz
from sqlalchemy.orm import Session

from utils.symbol_helpers import format_contract, is_option_symbol

from models import Position, Strategy, Trade, User
from notifications.email import is_enabled_for, send_report_async, send_test_report

logger = logging.getLogger(__name__)

ET = pytz.timezone("US/Eastern")

PERIODS = ("daily", "weekly", "monthly", "quarterly", "yearly")
ALWAYS_SEND_PERIODS = {"monthly", "quarterly", "yearly"}  # never skip on empty


# ───────────────────────────── window math ──────────────────────────────

def _et_midnight(d: date) -> datetime:
    """Localized midnight ET as a tz-aware datetime."""
    return ET.localize(datetime.combine(d, time(0, 0, 0)))


def _to_utc_naive(dt_et: datetime) -> datetime:
    """SQLAlchemy timestamp columns are naive UTC in this codebase, so
    return a naive UTC datetime to compare against `Trade.exit_timestamp`."""
    return dt_et.astimezone(pytz.utc).replace(tzinfo=None)


def _quarter_start(d: date) -> date:
    q_first_month = ((d.month - 1) // 3) * 3 + 1
    return date(d.year, q_first_month, 1)


def period_window_utc(period: str, anchor: date) -> Tuple[datetime, datetime]:
    """Return [start_utc, end_utc) for the given period anchored on `anchor`
    (a trading day in ET). End is the start of the next ET day."""
    if period == "daily":
        start = anchor
    elif period == "weekly":
        start = anchor - timedelta(days=anchor.weekday())  # Monday of this week
    elif period == "monthly":
        start = date(anchor.year, anchor.month, 1)
    elif period == "quarterly":
        start = _quarter_start(anchor)
    elif period == "yearly":
        start = date(anchor.year, 1, 1)
    else:
        raise ValueError(f"unknown period: {period}")

    start_utc = _to_utc_naive(_et_midnight(start))
    end_utc = _to_utc_naive(_et_midnight(anchor + timedelta(days=1)))
    return start_utc, end_utc


def period_label(period: str, anchor: date) -> str:
    """Human-readable label for the email subject + heading."""
    if period == "daily":
        return f"Daily — {anchor.strftime('%b %-d, %Y')}"
    if period == "weekly":
        start = anchor - timedelta(days=anchor.weekday())
        return f"Weekly — {start.strftime('%b %-d')}–{anchor.strftime('%b %-d, %Y')}"
    if period == "monthly":
        return f"Monthly — {anchor.strftime('%B %Y')}"
    if period == "quarterly":
        q = (anchor.month - 1) // 3 + 1
        return f"Quarterly — Q{q} {anchor.year}"
    if period == "yearly":
        return f"Yearly — {anchor.year}"
    return period


# ───────────────────────────── aggregation ──────────────────────────────

@dataclass
class StrategyRow:
    name: str
    trades: int
    wins: int
    losses: int
    pnl: float
    commission: float
    fees: float
    cost: float      # Total capital deployed (entry x qty x multiplier)


@dataclass
class TradeRow:
    when: datetime  # exit_timestamp UTC
    symbol: str
    strategy: str
    qty: int
    entry: float     # Premium per share
    exit: float      # Premium per share
    cost: float      # Total entry cost (entry × qty × multiplier)
    proceeds: float  # Total exit proceeds (exit × qty × multiplier)
    pnl: float


@dataclass
class ReportData:
    period: str
    label: str
    user_email: str
    user_name: str
    total_pnl: float
    total_commission: float
    total_fees: float
    trade_count: int
    win_count: int
    loss_count: int
    win_rate: Optional[float]   # None when trade_count == 0
    # Capital actually committed over the period, and what came back. The
    # premium alone ($2.23) says nothing about exposure; $223 per contract does.
    total_cost: float
    total_proceeds: float
    # Realized P&L as a % of capital deployed. None when nothing was deployed.
    return_on_capital: Optional[float]
    by_strategy: List[StrategyRow]
    trades: List[TradeRow]      # sorted desc by exit time, capped


_TRADES_TABLE_CAP = 50


def aggregate(db: Session, user: User, period: str, anchor: date) -> ReportData:
    start_utc, end_utc = period_window_utc(period, anchor)

    # Closed trades only — the report is about realized PnL. exit_timestamp
    # is set when a position is closed (order_manager._update_position_exit
    # / close_position). Both buys and sells appear in Trade; the closing
    # leg is what carries the PnL.
    # Position is joined for `option_symbol`: Trade.symbol is the UNDERLYING
    # ("SPY"), never the OCC contract, so `is_option_symbol(trade.symbol)` is
    # always False and the 100x contract multiplier was never applied — Cost
    # and Proceeds read $2.23 where $223 was actually at risk. The broker
    # position row is the only place the contract identity is recorded.
    # Same join routers/performance.py uses for the same reason.
    rows = (
        db.query(Trade, Strategy, Position)
        .outerjoin(Strategy, Trade.strategy_id == Strategy.id)
        .outerjoin(Position, Trade.position_id == Position.id)
        .filter(
            Trade.user_id == user.id,
            Trade.exit_timestamp.isnot(None),
            Trade.exit_timestamp >= start_utc,
            Trade.exit_timestamp < end_utc,
            Trade.status == "executed",
        )
        .order_by(Trade.exit_timestamp.desc())
        .all()
    )

    by_strategy: Dict[str, StrategyRow] = {}
    trade_rows: List[TradeRow] = []
    total_pnl = 0.0
    total_commission = 0.0
    total_fees = 0.0
    total_cost = 0.0
    total_proceeds = 0.0
    win_count = 0
    loss_count = 0

    for trade, strategy, position in rows:
        pnl = float(trade.pnl or 0.0)
        commission = float(trade.commission or 0.0)
        fees = float(trade.fees or 0.0)
        total_pnl += pnl
        total_commission += commission
        total_fees += fees
        is_win = pnl >= 0
        if is_win:
            win_count += 1
        else:
            loss_count += 1

        qty = int(trade.filled_qty or trade.qty or 0)
        entry = float(trade.price or 0.0)
        exit_price = float(trade.exit_price or trade.price or 0.0)

        # The OCC contract. Trade notes FIRST: they are stamped at trade time and
        # never change. positions.option_symbol is mutable — a closed row is
        # reused by the next entry — so for any historical trade it names
        # whatever was bought most recently, not what this trade closed. Only
        # fall back to it for older rows written before close_notes carried the
        # contract. Its presence, not the underlying's spelling, is what makes
        # this an options trade.
        occ = (trade.notes or {}).get('option_symbol') or (
            position.option_symbol if position else None
        )

        # Total cost and proceeds. Options are quoted per share and trade in
        # 100-share contracts, so a $2.23 premium on 1 contract is $223 of
        # capital actually committed — which is the number to report.
        # Computed for EVERY trade, not just the ones that fit the table cap,
        # so the header totals cover the whole period.
        multiplier = 100 if (occ or is_option_symbol(trade.symbol)) else 1
        cost = entry * qty * multiplier
        proceeds = exit_price * qty * multiplier
        total_cost += cost
        total_proceeds += proceeds

        sname = strategy.name if strategy else "(unlinked)"
        if sname not in by_strategy:
            by_strategy[sname] = StrategyRow(
                name=sname, trades=0, wins=0, losses=0,
                pnl=0.0, commission=0.0, fees=0.0, cost=0.0,
            )
        s = by_strategy[sname]
        s.trades += 1
        s.wins += 1 if is_win else 0
        s.losses += 0 if is_win else 1
        s.pnl += pnl
        s.commission += commission
        s.fees += fees
        s.cost += cost

        if len(trade_rows) < _TRADES_TABLE_CAP:
            trade_rows.append(TradeRow(
                when=trade.exit_timestamp,
                symbol=occ or trade.symbol,
                strategy=sname,
                qty=qty,
                entry=entry,
                exit=exit_price,
                cost=cost,
                proceeds=proceeds,
                pnl=pnl,
            ))

    trade_count = win_count + loss_count
    win_rate = (win_count / trade_count) if trade_count else None

    return ReportData(
        period=period,
        label=period_label(period, anchor),
        user_email=user.email,
        user_name=user.name or user.email,
        total_pnl=total_pnl,
        total_commission=total_commission,
        total_fees=total_fees,
        trade_count=trade_count,
        win_count=win_count,
        loss_count=loss_count,
        win_rate=win_rate,
        total_cost=total_cost,
        total_proceeds=total_proceeds,
        return_on_capital=(total_pnl / total_cost) if total_cost > 0.01 else None,
        by_strategy=sorted(by_strategy.values(), key=lambda r: r.pnl, reverse=True),
        trades=trade_rows,
    )


# ───────────────────────────── rendering ────────────────────────────────

def _money(v: float) -> str:
    sign = "-" if v < 0 else ""
    return f"{sign}${abs(v):,.2f}"


def _signed(v: float) -> str:
    return f"{'+' if v >= 0 else ''}{_money(v)}"


def _pct(v: Optional[float]) -> str:
    return "—" if v is None else f"{v * 100:.1f}%"


# Palette. Deliberately literal hex, NOT the UI's CSS custom properties: email
# clients strip <style> blocks and have no :root to resolve var() against, so
# every colour has to be inline. This is the one place hardcoded hex is correct.
_INK = "#111827"
_MUTED = "#6b7280"
_FAINT = "#9ca3af"
_LINE = "#e5e7eb"
_ZEBRA = "#fafafa"
_WIN = "#15803d"
_LOSS = "#b91c1c"
_WIN_BG = "#f0fdf4"
_LOSS_BG = "#fef2f2"

# Right-aligned numeric cells use tabular figures so decimal points line up
# across rows in clients that honour font-variant-numeric (most modern ones).
_NUM = (
    "font-variant-numeric:tabular-nums;font-feature-settings:'tnum';"
    "font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;"
)


def _tile(label: str, value: str, color: str = _INK) -> str:
    """One stat cell in the summary grid."""
    return (
        f'<td style="padding:10px 12px;border:1px solid {_LINE};border-radius:6px;'
        f'background:#fff;" width="33%">'
        f'<div style="font-size:10px;color:{_MUTED};text-transform:uppercase;'
        f'letter-spacing:.6px;">{label}</div>'
        f'<div style="font-size:17px;font-weight:600;color:{color};margin-top:3px;{_NUM}">'
        f'{value}</div></td>'
    )


def _tile_row(tiles: list) -> str:
    cells = '<td style="width:8px;"></td>'.join(tiles)
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'style="border-collapse:separate;margin:0 0 10px;"><tr>' + cells + '</tr></table>'
    )


def render_html(data: ReportData) -> str:
    """Self-contained HTML — no external CSS. Uses inline styles only;
    Gmail/Outlook strip <style> blocks unpredictably, and neither supports
    CSS custom properties, so the UI's theme tokens cannot be used here."""
    pnl_color = _WIN if data.total_pnl >= 0 else _LOSS
    pnl_bg = _WIN_BG if data.total_pnl >= 0 else _LOSS_BG

    roc = _pct(data.return_on_capital)

    summary = f"""
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
           style="border-collapse:collapse;margin:0 0 10px;">
      <tr>
        <td style="padding:16px 18px;background:{pnl_bg};border-radius:8px;
                   border:1px solid {pnl_color}22;">
          <div style="font-size:10px;color:{_MUTED};text-transform:uppercase;letter-spacing:.8px;">
            Total realized P&amp;L
          </div>
          <div style="font-size:32px;font-weight:700;color:{pnl_color};margin-top:2px;{_NUM}">
            {_signed(data.total_pnl)}
          </div>
          <div style="font-size:12px;color:{_MUTED};margin-top:4px;">
            {roc} return on {_money(data.total_cost)} deployed
          </div>
        </td>
      </tr>
    </table>
    {_tile_row([
        _tile("Trades", str(data.trade_count)),
        _tile("Win rate", _pct(data.win_rate)),
        _tile("W / L", f"{data.win_count} / {data.loss_count}"),
    ])}
    {_tile_row([
        _tile("Capital deployed", _money(data.total_cost)),
        _tile("Proceeds", _money(data.total_proceeds)),
        _tile("Return on capital", roc, pnl_color),
    ])}
    <div style="font-size:11px;color:{_FAINT};margin:8px 0 20px;">
      Commission {_money(data.total_commission)}
      &nbsp;&middot;&nbsp;
      Fees {_money(data.total_fees)}
      &nbsp;&middot;&nbsp;
      Net after costs {_signed(data.total_pnl - data.total_commission - data.total_fees)}
    </div>
    """

    if data.by_strategy:
        rows = "".join(
            f"""<tr style="background:{_ZEBRA if i % 2 else '#fff'};">
              <td style="padding:9px 12px;border-bottom:1px solid {_LINE};">{s.name}</td>
              <td style="padding:9px 12px;border-bottom:1px solid {_LINE};text-align:right;{_NUM}">{s.trades}</td>
              <td style="padding:9px 12px;border-bottom:1px solid {_LINE};text-align:right;{_NUM}">{s.wins}/{s.losses}</td>
              <td style="padding:9px 12px;border-bottom:1px solid {_LINE};text-align:right;{_NUM}">{_money(s.cost)}</td>
              <td style="padding:9px 12px;border-bottom:1px solid {_LINE};text-align:right;font-weight:600;{_NUM}
                         color:{_WIN if s.pnl >= 0 else _LOSS};">{_signed(s.pnl)}</td>
            </tr>"""
            for i, s in enumerate(data.by_strategy)
        )
        strategies_block = f"""
        <h3 style="font-size:12px;color:{_MUTED};margin:24px 0 8px;text-transform:uppercase;
                   letter-spacing:.6px;">By strategy</h3>
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
               style="border-collapse:collapse;font-size:13px;border:1px solid {_LINE};
                      border-radius:6px;overflow:hidden;">
          <thead>
            <tr style="background:#f3f4f6;">
              <th style="padding:8px 12px;text-align:left;font-size:11px;color:{_MUTED};
                         text-transform:uppercase;letter-spacing:.5px;">Strategy</th>
              <th style="padding:8px 12px;text-align:right;font-size:11px;color:{_MUTED};
                         text-transform:uppercase;letter-spacing:.5px;">Trades</th>
              <th style="padding:8px 12px;text-align:right;font-size:11px;color:{_MUTED};
                         text-transform:uppercase;letter-spacing:.5px;">W/L</th>
              <th style="padding:8px 12px;text-align:right;font-size:11px;color:{_MUTED};
                         text-transform:uppercase;letter-spacing:.5px;">Capital</th>
              <th style="padding:8px 12px;text-align:right;font-size:11px;color:{_MUTED};
                         text-transform:uppercase;letter-spacing:.5px;">P&amp;L</th>
            </tr>
          </thead>
          <tbody>{rows}</tbody>
        </table>
        """
    else:
        strategies_block = ""

    if data.trades:
        def _trade_row(i: int, t: TradeRow) -> str:
            c = _WIN if t.pnl >= 0 else _LOSS
            ret = (t.pnl / t.cost * 100) if t.cost > 0.01 else None
            cell = f"padding:8px;border-bottom:1px solid {_LINE};"
            return f"""<tr style="background:{_ZEBRA if i % 2 else '#fff'};">
              <td style="{cell}color:{_FAINT};white-space:nowrap;">{t.when.strftime('%m/%d %H:%M')}</td>
              <td style="{cell}font-weight:600;white-space:nowrap;">{format_contract(t.symbol, t.symbol)}</td>
              <td style="{cell}text-align:right;{_NUM}">{t.qty}</td>
              <td style="{cell}text-align:right;color:{_MUTED};{_NUM}">
                ${t.entry:.2f} &rarr; ${t.exit:.2f}</td>
              <td style="{cell}text-align:right;{_NUM}">{_money(t.cost)}</td>
              <td style="{cell}text-align:right;{_NUM}">{_money(t.proceeds)}</td>
              <td style="{cell}text-align:right;font-weight:600;color:{c};{_NUM}">{_signed(t.pnl)}</td>
              <td style="{cell}text-align:right;color:{c};{_NUM}">
                {'—' if ret is None else f'{ret:+.1f}%'}</td>
            </tr>"""

        trade_rows = "".join(_trade_row(i, t) for i, t in enumerate(data.trades))
        cap_note = ""
        if data.trade_count > _TRADES_TABLE_CAP:
            cap_note = (
                f'<div style="font-size:11px;color:{_FAINT};margin-top:6px;">'
                f'Showing {_TRADES_TABLE_CAP} most recent of {data.trade_count} trades. '
                f'Totals above cover all {data.trade_count}.</div>'
            )
        th = (f'padding:8px;text-align:right;font-size:10px;color:{_MUTED};'
              f'text-transform:uppercase;letter-spacing:.5px;white-space:nowrap;')
        trades_block = f"""
        <h3 style="font-size:12px;color:{_MUTED};margin:24px 0 8px;text-transform:uppercase;
                   letter-spacing:.6px;">Closed trades</h3>
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
               style="border-collapse:collapse;font-size:12px;border:1px solid {_LINE};
                      border-radius:6px;overflow:hidden;">
          <thead>
            <tr style="background:#f3f4f6;">
              <th style="{th}text-align:left;">Time</th>
              <th style="{th}text-align:left;">Contract</th>
              <th style="{th}">Qty</th>
              <th style="{th}">Entry &rarr; Exit</th>
              <th style="{th}">Cost</th>
              <th style="{th}">Proceeds</th>
              <th style="{th}">P&amp;L</th>
              <th style="{th}">Return</th>
            </tr>
          </thead>
          <tbody>{trade_rows}</tbody>
        </table>
        {cap_note}
        """
    else:
        trades_block = (
            f'<div style="color:{_FAINT};font-size:13px;margin:24px 0 8px;">'
            f'No closed trades in this period.</div>'
        )

    return f"""<!doctype html>
<html><body style="margin:0;padding:24px;background:#f3f4f6;
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;color:{_INK};">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
         style="max-width:720px;margin:0 auto;background:#fff;border-radius:10px;
                padding:26px;border:1px solid {_LINE};">
    <tr><td>
      <div style="font-size:10px;color:{_FAINT};text-transform:uppercase;letter-spacing:1.4px;
                  font-weight:600;">VegaPunkR</div>
      <h1 style="font-size:19px;color:{_INK};margin:6px 0 2px;font-weight:600;">{data.label}</h1>
      <div style="font-size:12px;color:{_MUTED};margin-bottom:18px;">Hi {data.user_name},</div>
      {summary}
      {strategies_block}
      {trades_block}
      <div style="font-size:11px;color:{_FAINT};margin-top:30px;border-top:1px solid {_LINE};
                  padding-top:12px;line-height:1.5;">
        Options are quoted per share and trade in 100-share contracts &mdash; Cost and
        Proceeds are the dollars actually committed, not the premium.<br>
        Sent to {data.user_email}. Toggle these reports in the user menu under &ldquo;Email reports&rdquo;.
      </div>
    </td></tr>
  </table>
</body></html>"""


def render_text(data: ReportData) -> str:
    """Plain-text fallback for clients that strip HTML."""
    lines = [
        f"VegaPunkR — {data.label}",
        f"Hi {data.user_name},",
        "",
        f"Total realized P&L: {_signed(data.total_pnl)}",
        f"Trades: {data.trade_count}  |  Wins/Losses: {data.win_count}/{data.loss_count}  |  Win rate: {_pct(data.win_rate)}",
        f"Capital deployed: {_money(data.total_cost)}  |  Proceeds: {_money(data.total_proceeds)}"
        f"  |  Return on capital: {_pct(data.return_on_capital)}",
        f"Commission: {_money(data.total_commission)}  |  Fees: {_money(data.total_fees)}"
        f"  |  Net after costs: {_signed(data.total_pnl - data.total_commission - data.total_fees)}",
    ]
    if data.by_strategy:
        lines.append("")
        lines.append("By strategy:")
        for s in data.by_strategy:
            lines.append(
                f"  {s.name}: {s.trades} trades, {s.wins}W/{s.losses}L, "
                f"capital {_money(s.cost)}, {_signed(s.pnl)}"
            )
    if data.trades:
        lines.append("")
        lines.append(f"Closed trades ({len(data.trades)} of {data.trade_count}):")
        header = (
            f"  {'Time':<12} {'Contract':<22} {'Qty':>4}  {'Entry':>7} {'Exit':>7}  "
            f"{'Cost':>10} {'Proceeds':>10}  {'P&L':>10} {'Return':>8}"
        )
        lines.append(header)
        lines.append("  " + "-" * (len(header) - 2))
        for t in data.trades:
            ret = f"{t.pnl / t.cost * 100:+.1f}%" if t.cost > 0.01 else "—"
            lines.append(
                f"  {t.when.strftime('%m/%d %H:%M'):<12} "
                f"{format_contract(t.symbol, t.symbol):<22} {t.qty:>4}  "
                f"{t.entry:>7.2f} {t.exit:>7.2f}  "
                f"{_money(t.cost):>10} {_money(t.proceeds):>10}  "
                f"{_signed(t.pnl):>10} {ret:>8}"
            )
    else:
        lines.append("")
        lines.append("No closed trades in this period.")
    lines.append("")
    lines.append(f"Sent to {data.user_email}. Toggle these in the user menu under 'Email reports'.")
    return "\n".join(lines)


def subject_for(data: ReportData) -> str:
    return f"VegaPunkR {data.label} — P&L {_signed(data.total_pnl)}"


# ───────────────────────────── dispatch ─────────────────────────────────

def send_report(db: Session, user: User, period: str, anchor: date) -> Optional[ReportData]:
    """Aggregate, render, and async-dispatch a report for one user/period.

    Returns the rendered ReportData on send; returns None when the period
    has no trades and the rule says to skip (daily/weekly only).
    """
    data = aggregate(db, user, period, anchor)
    if data.trade_count == 0 and period not in ALWAYS_SEND_PERIODS:
        logger.info(
            f"email: skipping {period} report for {user.email} — no closed trades"
        )
        return None

    html = render_html(data)
    text = render_text(data)
    subject = subject_for(data)
    send_report_async(user.email, subject, html, text)
    return data


def send_test_now(db: Session, user: User) -> Tuple[bool, str]:
    """Real-shaped daily report against today's trades. Used by the
    'Send test report' button so the user can verify formatting +
    deliverability before saving prefs."""
    today_et = datetime.now(ET).date()
    data = aggregate(db, user, "daily", today_et)
    # Override the heading so the user can tell at a glance this was the
    # test button, not a scheduled send.
    data.label = f"Test report — {data.label}"
    html = render_html(data)
    text = render_text(data)
    subject = f"[TEST] {subject_for(data)}"
    return send_test_report(user.email, subject, html, text)


# ──────────────────────── period firing rules ───────────────────────────

def _yyyymmdd(d: date) -> str:
    return d.strftime("%Y-%m-%d")


def fires_today(period: str, anchor: date, calendar_days: List[Dict]) -> bool:
    """True if `period` should send a report on `anchor` (a trading day in
    ET). `calendar_days` is the Tradier `markets/calendar` day list for
    the current month (and ideally next month too for end-of-month edge
    cases)."""
    if period == "daily":
        return True

    # Find the next trading day strictly after `anchor`. If none in the
    # provided calendar, treat as last-of-period (caller should pass in
    # next month too around month boundaries).
    next_open: Optional[date] = None
    anchor_str = _yyyymmdd(anchor)
    seen_anchor = False
    for d in calendar_days:
        if d.get("status") != "open":
            continue
        d_str = str(d.get("date") or "")
        if d_str == anchor_str:
            seen_anchor = True
            continue
        if seen_anchor:
            try:
                next_open = datetime.strptime(d_str, "%Y-%m-%d").date()
            except ValueError:
                continue
            break

    if next_open is None:
        # No subsequent open day in the provided window — assume this is
        # the last trading day of the calendar window. For monthly+,
        # callers should always pass enough calendar coverage so this
        # path is rare; defaulting to True keeps the user from missing
        # a yearly report on Dec 31.
        return True

    if period == "weekly":
        # Last trading day of the ISO week
        return next_open.isocalendar()[:2] != anchor.isocalendar()[:2]
    if period == "monthly":
        return (next_open.year, next_open.month) != (anchor.year, anchor.month)
    if period == "quarterly":
        return _quarter_start(next_open) != _quarter_start(anchor)
    if period == "yearly":
        return next_open.year != anchor.year
    return False
