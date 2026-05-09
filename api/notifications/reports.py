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

from models import Strategy, Trade, User
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


@dataclass
class TradeRow:
    when: datetime  # exit_timestamp UTC
    symbol: str
    strategy: str
    qty: int
    entry: float
    exit: float
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
    by_strategy: List[StrategyRow]
    trades: List[TradeRow]      # sorted desc by exit time, capped


_TRADES_TABLE_CAP = 50


def aggregate(db: Session, user: User, period: str, anchor: date) -> ReportData:
    start_utc, end_utc = period_window_utc(period, anchor)

    # Closed trades only — the report is about realized PnL. exit_timestamp
    # is set when a position is closed (order_manager._update_position_exit
    # / close_position). Both buys and sells appear in Trade; the closing
    # leg is what carries the PnL.
    rows = (
        db.query(Trade, Strategy)
        .outerjoin(Strategy, Trade.strategy_id == Strategy.id)
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
    win_count = 0
    loss_count = 0

    for trade, strategy in rows:
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

        sname = strategy.name if strategy else "(unlinked)"
        if sname not in by_strategy:
            by_strategy[sname] = StrategyRow(
                name=sname, trades=0, wins=0, losses=0,
                pnl=0.0, commission=0.0, fees=0.0,
            )
        s = by_strategy[sname]
        s.trades += 1
        s.wins += 1 if is_win else 0
        s.losses += 0 if is_win else 1
        s.pnl += pnl
        s.commission += commission
        s.fees += fees

        if len(trade_rows) < _TRADES_TABLE_CAP:
            trade_rows.append(TradeRow(
                when=trade.exit_timestamp,
                symbol=trade.symbol,
                strategy=sname,
                qty=int(trade.filled_qty or trade.qty or 0),
                entry=float(trade.price or 0.0),
                exit=float(trade.exit_price or trade.price or 0.0),
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


def render_html(data: ReportData) -> str:
    """Self-contained HTML — no external CSS. Uses inline styles only;
    Gmail/Outlook strip <style> blocks unpredictably."""
    pnl_color = "#1b5e20" if data.total_pnl >= 0 else "#b71c1c"
    pnl_bg = "#e8f5e9" if data.total_pnl >= 0 else "#ffebee"

    summary = f"""
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
           style="border-collapse:collapse;margin:0 0 16px;">
      <tr>
        <td style="padding:12px 16px;background:{pnl_bg};border-radius:6px;">
          <div style="font-size:11px;color:#555;text-transform:uppercase;letter-spacing:0.5px;">
            Total realized P&amp;L
          </div>
          <div style="font-size:24px;font-weight:600;color:{pnl_color};margin-top:2px;">
            {_signed(data.total_pnl)}
          </div>
        </td>
      </tr>
    </table>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
           style="border-collapse:collapse;margin:0 0 20px;">
      <tr>
        <td style="padding:8px 12px;border:1px solid #ddd;border-radius:4px;width:33%;">
          <div style="font-size:11px;color:#666;text-transform:uppercase;">Trades</div>
          <div style="font-size:18px;font-weight:600;">{data.trade_count}</div>
        </td>
        <td style="width:8px;"></td>
        <td style="padding:8px 12px;border:1px solid #ddd;border-radius:4px;width:33%;">
          <div style="font-size:11px;color:#666;text-transform:uppercase;">Win rate</div>
          <div style="font-size:18px;font-weight:600;">{_pct(data.win_rate)}</div>
        </td>
        <td style="width:8px;"></td>
        <td style="padding:8px 12px;border:1px solid #ddd;border-radius:4px;width:33%;">
          <div style="font-size:11px;color:#666;text-transform:uppercase;">W / L</div>
          <div style="font-size:18px;font-weight:600;">{data.win_count} / {data.loss_count}</div>
        </td>
      </tr>
    </table>
    <div style="font-size:12px;color:#666;margin:0 0 20px;">
      Commission: {_money(data.total_commission)}
      &nbsp;&middot;&nbsp;
      Fees: {_money(data.total_fees)}
    </div>
    """

    if data.by_strategy:
        rows = "".join(
            f"""<tr>
              <td style="padding:8px 12px;border-bottom:1px solid #eee;">{s.name}</td>
              <td style="padding:8px 12px;border-bottom:1px solid #eee;text-align:right;">{s.trades}</td>
              <td style="padding:8px 12px;border-bottom:1px solid #eee;text-align:right;">{s.wins}/{s.losses}</td>
              <td style="padding:8px 12px;border-bottom:1px solid #eee;text-align:right;color:{'#1b5e20' if s.pnl >= 0 else '#b71c1c'};">{_signed(s.pnl)}</td>
            </tr>"""
            for s in data.by_strategy
        )
        strategies_block = f"""
        <h3 style="font-size:14px;color:#333;margin:24px 0 8px;">By strategy</h3>
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
               style="border-collapse:collapse;font-size:13px;">
          <thead>
            <tr style="background:#fafafa;">
              <th style="padding:8px 12px;text-align:left;border-bottom:1px solid #ddd;">Strategy</th>
              <th style="padding:8px 12px;text-align:right;border-bottom:1px solid #ddd;">Trades</th>
              <th style="padding:8px 12px;text-align:right;border-bottom:1px solid #ddd;">W/L</th>
              <th style="padding:8px 12px;text-align:right;border-bottom:1px solid #ddd;">P&amp;L</th>
            </tr>
          </thead>
          <tbody>{rows}</tbody>
        </table>
        """
    else:
        strategies_block = ""

    if data.trades:
        trade_rows = "".join(
            f"""<tr>
              <td style="padding:6px 10px;border-bottom:1px solid #f0f0f0;color:#666;">{t.when.strftime('%m/%d %H:%M')}</td>
              <td style="padding:6px 10px;border-bottom:1px solid #f0f0f0;font-family:monospace;">{t.symbol}</td>
              <td style="padding:6px 10px;border-bottom:1px solid #f0f0f0;color:#666;">{t.strategy}</td>
              <td style="padding:6px 10px;border-bottom:1px solid #f0f0f0;text-align:right;">{t.qty}</td>
              <td style="padding:6px 10px;border-bottom:1px solid #f0f0f0;text-align:right;">{_money(t.entry)}</td>
              <td style="padding:6px 10px;border-bottom:1px solid #f0f0f0;text-align:right;">{_money(t.exit)}</td>
              <td style="padding:6px 10px;border-bottom:1px solid #f0f0f0;text-align:right;color:{'#1b5e20' if t.pnl >= 0 else '#b71c1c'};">{_signed(t.pnl)}</td>
            </tr>"""
            for t in data.trades
        )
        cap_note = ""
        if data.trade_count > _TRADES_TABLE_CAP:
            cap_note = f'<div style="font-size:11px;color:#999;margin-top:6px;">Showing {_TRADES_TABLE_CAP} most recent of {data.trade_count} trades.</div>'
        trades_block = f"""
        <h3 style="font-size:14px;color:#333;margin:24px 0 8px;">Closed trades</h3>
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
               style="border-collapse:collapse;font-size:12px;">
          <thead>
            <tr style="background:#fafafa;">
              <th style="padding:6px 10px;text-align:left;border-bottom:1px solid #ddd;">Time</th>
              <th style="padding:6px 10px;text-align:left;border-bottom:1px solid #ddd;">Symbol</th>
              <th style="padding:6px 10px;text-align:left;border-bottom:1px solid #ddd;">Strategy</th>
              <th style="padding:6px 10px;text-align:right;border-bottom:1px solid #ddd;">Qty</th>
              <th style="padding:6px 10px;text-align:right;border-bottom:1px solid #ddd;">Entry</th>
              <th style="padding:6px 10px;text-align:right;border-bottom:1px solid #ddd;">Exit</th>
              <th style="padding:6px 10px;text-align:right;border-bottom:1px solid #ddd;">P&amp;L</th>
            </tr>
          </thead>
          <tbody>{trade_rows}</tbody>
        </table>
        {cap_note}
        """
    else:
        trades_block = '<div style="color:#888;font-size:13px;margin:24px 0 8px;">No closed trades in this period.</div>'

    return f"""<!doctype html>
<html><body style="margin:0;padding:24px;background:#f5f5f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#222;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:680px;margin:0 auto;background:#fff;border-radius:8px;padding:24px;">
    <tr><td>
      <div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:1px;">VegaPunkR</div>
      <h1 style="font-size:20px;color:#222;margin:4px 0 16px;">{data.label}</h1>
      <div style="font-size:13px;color:#666;margin-bottom:16px;">Hi {data.user_name},</div>
      {summary}
      {strategies_block}
      {trades_block}
      <div style="font-size:11px;color:#999;margin-top:32px;border-top:1px solid #eee;padding-top:12px;">
        Sent to {data.user_email}. Toggle these reports in the user menu under "Email reports".
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
        f"Commission: {_money(data.total_commission)}  |  Fees: {_money(data.total_fees)}",
    ]
    if data.by_strategy:
        lines.append("")
        lines.append("By strategy:")
        for s in data.by_strategy:
            lines.append(f"  {s.name}: {s.trades} trades, {s.wins}W/{s.losses}L, {_signed(s.pnl)}")
    if data.trades:
        lines.append("")
        lines.append(f"Closed trades ({len(data.trades)} of {data.trade_count}):")
        for t in data.trades:
            lines.append(
                f"  {t.when.strftime('%m/%d %H:%M')}  {t.symbol:<24} "
                f"{t.qty:>4}  entry {_money(t.entry):>10}  exit {_money(t.exit):>10}  "
                f"P&L {_signed(t.pnl)}"
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
