"""
Resend-backed email transport for end-of-period reports.

Per-user opt-in: reads `User.notification_preferences['email_reports']`,
shaped as:

    {
        "enabled": bool,
        "daily": bool,
        "weekly": bool,
        "monthly": bool,
        "quarterly": bool,
        "yearly": bool,
    }

The `to` address is always `User.email` — there's no separate report-only
address. All sends are best-effort and fired from a daemon thread so a
slow Resend response can't stall the dispatch loop. Failures are logged
and swallowed.

Without `RESEND_API_KEY` set, sends are skipped (a no-op + INFO log) so
dev environments don't need a Resend account to exercise the code path.
"""
import logging
import threading
from typing import Any, Dict, Optional, Tuple

from config import settings

logger = logging.getLogger(__name__)


def _email_prefs(user_prefs: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    return ((user_prefs or {}).get("email_reports") or {}) if isinstance(user_prefs, dict) else {}


def is_enabled_for(user_prefs: Optional[Dict[str, Any]], period: str) -> bool:
    """Top-level toggle AND per-period toggle must both be true."""
    prefs = _email_prefs(user_prefs)
    if not prefs.get("enabled"):
        return False
    return bool(prefs.get(period, False))


def _from_address() -> str:
    name = settings.EMAIL_FROM_NAME or "VegaPunkR Reports"
    addr = settings.EMAIL_FROM_ADDRESS or "reports@vegapunkr.local"
    return f"{name} <{addr}>"


def _send_via_resend(to: str, subject: str, html: str, text: str) -> Tuple[bool, str]:
    """Synchronous Resend send. Returns (ok, message). No raises — callers
    decide whether failure is fatal."""
    api_key = settings.RESEND_API_KEY
    if not api_key:
        logger.info(
            f"email: RESEND_API_KEY not set — skipping send to {to} "
            f"(subject: {subject!r}); rendered body suppressed in logs."
        )
        return True, "RESEND_API_KEY not set — send skipped (dev mode)."
    try:
        import resend  # imported lazily so test envs without the lib still load
    except ImportError:
        return False, "resend package not installed (pip install resend)"

    resend.api_key = api_key
    try:
        resp = resend.Emails.send({
            "from": _from_address(),
            "to": [to],
            "subject": subject,
            "html": html,
            "text": text,
        })
        msg_id = (resp or {}).get("id") if isinstance(resp, dict) else None
        return True, f"Email sent (id={msg_id})" if msg_id else "Email sent"
    except Exception as e:
        return False, f"Resend error: {e}"


def send_report_async(to: str, subject: str, html: str, text: str) -> None:
    """Fire-and-forget send for the scheduled dispatch loop. Daemon thread
    so a slow Resend call can't block iteration over remaining users."""
    def _send() -> None:
        ok, message = _send_via_resend(to, subject, html, text)
        if ok:
            logger.info(f"email: sent report to {to} — {message}")
        else:
            logger.warning(f"email: send to {to} failed — {message}")

    threading.Thread(target=_send, daemon=True).start()


def send_test_report(to: str, subject: str, html: str, text: str) -> Tuple[bool, str]:
    """Synchronous variant for the 'Send test report' button so the UI can
    surface the result inline."""
    return _send_via_resend(to, subject, html, text)
