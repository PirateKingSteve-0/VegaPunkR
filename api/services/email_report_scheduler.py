"""
Email report scheduler — two-stage anchor.

Stage 1: a daily APScheduler `CronTrigger` at 03:00 ET fetches today's
Tradier `markets/calendar` row. If today is a trading day, it schedules
a one-shot `DateTrigger` at the day's `open.end` (close) + 30 min ET.

Stage 2: the one-shot fires `dispatch()`, which iterates every user with
`notification_preferences.email_reports.enabled = true`, checks which
periods fire today (always daily; weekly/monthly/quarterly/yearly only
on the period's last trading day), and async-sends each.

Why two stages? A flat `CronTrigger(hour=16, minute=30)` would fire on
the wrong day for early-close holidays (e.g. day before Thanksgiving
closes at 13:00; a 16:30 dispatch would arrive at 16:30 even though the
session ended hours earlier).
"""
import logging
from datetime import date, datetime, time, timedelta
from typing import List, Optional

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from config import Environment
from database import SessionLocals, default_environment
from models import User
from notifications import reports
from notifications.email import is_enabled_for


def _new_session():
    """Session for this process's environment (APP_ENV, default dev), matching
    the engine worker. So a live-test process launched with APP_ENV=prod reports
    on prod data rather than always dev."""
    return SessionLocals[default_environment()]()

logger = logging.getLogger(__name__)

ET = pytz.timezone("US/Eastern")

DISPATCH_DELAY_MINUTES = 30
ANCHOR_HOUR_ET = 3  # daily 03:00 ET cron fires the calendar lookup
DISPATCH_JOB_ID = "email_reports_dispatch"
ANCHOR_JOB_ID = "email_reports_anchor"


def _today_et() -> date:
    return datetime.now(ET).date()


def _fetch_calendar_window(today: date) -> List[dict]:
    """Pull the current month's calendar plus the next month's so the
    last-trading-day-of-month detector works right at month boundaries."""
    try:
        from tradier_integration.client import get_tradier_client
        client = get_tradier_client()
        days = client.get_market_calendar(month=today.month, year=today.year)
        # Append next month so fires_today() can find a "next trading day"
        # even if today is the very last day of the month.
        next_month_year = today.year + (1 if today.month == 12 else 0)
        next_month = 1 if today.month == 12 else today.month + 1
        days += client.get_market_calendar(month=next_month, year=next_month_year)
        return days
    except Exception as e:
        logger.warning(f"email_reports: calendar fetch failed: {e}")
        return []


def _today_close_et(today: date, calendar_days: List[dict]) -> Optional[time]:
    """Return today's market close time (ET) per the calendar, or None
    if today is closed (weekend/holiday)."""
    target = today.strftime("%Y-%m-%d")
    for d in calendar_days:
        if str(d.get("date")) == target:
            if d.get("status") != "open":
                return None
            close_str = (d.get("open") or {}).get("end") or "16:00"
            try:
                hh, mm = close_str.split(":")
                return time(int(hh), int(mm))
            except (ValueError, AttributeError):
                return time(16, 0)
    return None  # not found in calendar — treat as non-trading


def _dispatch_at(close_et: time, today: date) -> datetime:
    """Wall-clock UTC datetime to fire the dispatch one-shot."""
    fire_et = ET.localize(datetime.combine(today, close_et)) + timedelta(minutes=DISPATCH_DELAY_MINUTES)
    return fire_et.astimezone(pytz.utc)


class EmailReportScheduler:
    def __init__(self) -> None:
        self.scheduler = AsyncIOScheduler(timezone=ET)
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        # Stage 1 — daily anchor at 03:00 ET. Fires `_anchor_today` which
        # decides whether today is a trading day and (if so) schedules the
        # close+30 dispatch.
        self.scheduler.add_job(
            self._anchor_today,
            trigger=CronTrigger(hour=ANCHOR_HOUR_ET, minute=0, timezone=ET),
            id=ANCHOR_JOB_ID,
            replace_existing=True,
            max_instances=1,
        )
        self.scheduler.start()
        self._started = True
        logger.info(
            "email_reports: scheduler started — daily anchor at "
            f"{ANCHOR_HOUR_ET:02d}:00 ET, dispatch at close+{DISPATCH_DELAY_MINUTES}min"
        )
        # Run an anchor immediately on startup so a same-day restart still
        # gets the dispatch scheduled (the cron only fires on subsequent
        # 03:00 ET ticks).
        try:
            self._anchor_today()
        except Exception as e:
            logger.warning(f"email_reports: startup anchor failed: {e}")

    def stop(self) -> None:
        if not self._started:
            return
        self.scheduler.shutdown(wait=False)
        self._started = False
        logger.info("email_reports: scheduler stopped")

    def _anchor_today(self) -> None:
        today = _today_et()
        calendar = _fetch_calendar_window(today)
        close_et = _today_close_et(today, calendar)
        if close_et is None:
            logger.info(f"email_reports: {today} is not a trading day — no dispatch scheduled")
            return

        fire_at_utc = _dispatch_at(close_et, today)
        if fire_at_utc <= datetime.utcnow().replace(tzinfo=pytz.utc):
            # Server started after close+30 — fire immediately so today's
            # report still goes out.
            logger.info(
                f"email_reports: dispatch window ({close_et.strftime('%H:%M')} ET + "
                f"{DISPATCH_DELAY_MINUTES}min) already past — dispatching now"
            )
            self.dispatch(today, calendar)
            return

        self.scheduler.add_job(
            self.dispatch,
            trigger=DateTrigger(run_date=fire_at_utc),
            args=[today, calendar],
            id=DISPATCH_JOB_ID,
            replace_existing=True,
            max_instances=1,
        )
        logger.info(
            f"email_reports: scheduled dispatch for {today} at "
            f"{fire_at_utc.astimezone(ET).strftime('%H:%M %Z')} "
            f"(close {close_et.strftime('%H:%M ET')} + {DISPATCH_DELAY_MINUTES}min)"
        )

    def dispatch(self, today: date, calendar: List[dict]) -> None:
        """Iterate users + periods, send what fires today. One DB query
        for the user list; per-user firing decisions and aggregations
        each get their own session so a slow query doesn't hold the
        connection across the whole run."""
        db = _new_session()
        try:
            users = (
                db.query(User)
                .filter(User.is_active.is_(True))
                .all()
            )
            opted_in = [u for u in users if (u.notification_preferences or {}).get("email_reports", {}).get("enabled")]
            logger.info(
                f"email_reports: dispatch for {today} — {len(opted_in)} opted-in users "
                f"(of {len(users)} active)"
            )
        finally:
            db.close()

        for user in opted_in:
            self._dispatch_one_user(user.id, today, calendar)

    def _dispatch_one_user(self, user_id: int, today: date, calendar: List[dict]) -> None:
        db = _new_session()
        try:
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                return
            prefs = user.notification_preferences or {}
            for period in reports.PERIODS:
                if not is_enabled_for(prefs, period):
                    continue
                if not reports.fires_today(period, today, calendar):
                    continue
                try:
                    reports.send_report(db, user, period, today)
                except Exception as e:
                    logger.error(
                        f"email_reports: send failed user={user.email} "
                        f"period={period}: {e}",
                        exc_info=True,
                    )
        finally:
            db.close()


_instance: Optional[EmailReportScheduler] = None


def get_email_report_scheduler() -> EmailReportScheduler:
    global _instance
    if _instance is None:
        _instance = EmailReportScheduler()
    return _instance
