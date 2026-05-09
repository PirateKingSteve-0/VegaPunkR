"""
Discord webhook notifications for trade opens and closes.

Per-user opt-in: reads `User.notification_preferences['discord']`, which is
shaped as:

    {
        "enabled": bool,
        "webhook_url": str,            # full Discord webhook URL
        "notify_open": bool,           # default True when missing
        "notify_close": bool,          # default True when missing
    }

All sends are best-effort and fired from a daemon thread so a slow or down
Discord webhook never blocks the post-fill path. Failures are logged and
swallowed — notifications must never crash the engine.
"""
import logging
import threading
from typing import Any, Dict, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

WEBHOOK_TIMEOUT_S = 5.0

_COLOR_GREEN = 0x2ECC71
_COLOR_RED = 0xE74C3C
_COLOR_BLUE = 0x3498DB

_VALID_HOSTS = (
    "https://discord.com/api/webhooks/",
    "https://discordapp.com/api/webhooks/",
    "https://canary.discord.com/api/webhooks/",
    "https://ptb.discord.com/api/webhooks/",
)


def is_valid_discord_webhook(url: Optional[str]) -> bool:
    """Guard against SSRF — only accept official Discord webhook hosts."""
    return bool(url) and url.startswith(_VALID_HOSTS)


def _discord_prefs(user_prefs: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    return ((user_prefs or {}).get("discord") or {}) if isinstance(user_prefs, dict) else {}


def _post_async(webhook_url: str, payload: Dict[str, Any]) -> None:
    def _send() -> None:
        try:
            requests.post(webhook_url, json=payload, timeout=WEBHOOK_TIMEOUT_S)
        except Exception as e:
            logger.warning(f"discord_notifier: webhook post failed: {e}")

    threading.Thread(target=_send, daemon=True).start()


def notify_position_opened(
    user_prefs: Optional[Dict[str, Any]],
    symbol: str,
    qty: int,
    price: float,
    strategy_name: Optional[str] = None,
    option_symbol: Optional[str] = None,
) -> None:
    discord = _discord_prefs(user_prefs)
    if not discord.get("enabled") or not discord.get("notify_open", True):
        return
    webhook = discord.get("webhook_url")
    if not is_valid_discord_webhook(webhook):
        return

    label = option_symbol or symbol
    fields = [
        {"name": "Qty", "value": str(qty), "inline": True},
        {"name": "Price", "value": f"${price:.2f}", "inline": True},
    ]
    if strategy_name:
        fields.append({"name": "Strategy", "value": strategy_name, "inline": False})

    _post_async(
        webhook,
        {
            "embeds": [
                {
                    "title": f"🟢 Opened {label}",
                    "color": _COLOR_GREEN,
                    "fields": fields,
                }
            ]
        },
    )


def notify_position_closed(
    user_prefs: Optional[Dict[str, Any]],
    symbol: str,
    qty: int,
    price: float,
    pnl: float,
    strategy_name: Optional[str] = None,
    option_symbol: Optional[str] = None,
) -> None:
    # Call sites (audited 2026-05-09 — exactly one fire per real fully-closed
    # position, never on bailout/retry):
    #   1. order_manager.close_position() — only after terminal status=='filled';
    #      every bailout (throttle, preview-fail, broker reject, unconfirmed,
    #      non-filled terminal, exception) returns before this notify.
    #   2. stream_driven_worker._reconcile_position() — only when broker shows
    #      flat AND local qty>0 (manual close in broker UI). Can't double-fire
    #      after #1 because reconcile early-returns when local qty<=0.
    #   3. order_manager._update_position_exit() — gated by fully_closed; only
    #      reachable via execute_signal('exit'), which strategy_executor never
    #      calls (exits route through close_position). Kept for safety.
    # Startup-sync manual closes in stream_driven_worker (~line 470) are
    # intentionally silent — cold-boot would burst stale embeds for closes
    # that happened while the server was down.
    discord = _discord_prefs(user_prefs)
    if not discord.get("enabled") or not discord.get("notify_close", True):
        return
    webhook = discord.get("webhook_url")
    if not is_valid_discord_webhook(webhook):
        return

    is_win = pnl >= 0
    color = _COLOR_GREEN if is_win else _COLOR_RED
    sign = "+" if pnl >= 0 else ""
    emoji = "🟢" if is_win else "🔴"
    label = option_symbol or symbol

    fields = [
        {"name": "Qty", "value": str(qty), "inline": True},
        {"name": "Exit", "value": f"${price:.2f}", "inline": True},
        {"name": "P&L", "value": f"{sign}${pnl:.2f}", "inline": True},
    ]
    if strategy_name:
        fields.append({"name": "Strategy", "value": strategy_name, "inline": False})

    _post_async(
        webhook,
        {
            "embeds": [
                {
                    "title": f"{emoji} Closed {label}",
                    "color": color,
                    "fields": fields,
                }
            ]
        },
    )


def send_test_message(webhook_url: str) -> Tuple[bool, str]:
    """Synchronous send used by the 'send test' button. Returns (ok, message)."""
    if not is_valid_discord_webhook(webhook_url):
        return False, "Webhook URL must be a Discord webhook URL."
    try:
        r = requests.post(
            webhook_url,
            json={
                "embeds": [
                    {
                        "title": "✅ VegaPunkR test message",
                        "description": "Discord notifications are wired up correctly.",
                        "color": _COLOR_BLUE,
                    }
                ]
            },
            timeout=WEBHOOK_TIMEOUT_S,
        )
        if r.status_code in (200, 204):
            return True, "Test message sent."
        return False, f"Discord returned HTTP {r.status_code}."
    except requests.RequestException as e:
        return False, f"Network error: {e}"
