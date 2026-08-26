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

from utils.symbol_helpers import format_contract, is_option_symbol

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


def _contract_multiplier(option_symbol: Optional[str], symbol: str) -> int:
    """100 for an options contract, 1 for equity.

    Options are quoted per share and trade in 100-share contracts, so the
    premium alone ("$2.23") says nothing about money at risk — $223 does.
    Both are worth showing; only one of them is the dollar figure.
    """
    return 100 if is_option_symbol(option_symbol or symbol) else 1


def _money(v: float) -> str:
    sign = "-" if v < 0 else ""
    return f"{sign}${abs(v):,.2f}"


def _signed_money(v: float) -> str:
    return f"{'+' if v >= 0 else ''}{_money(v)}"


def _table(rows: list) -> str:
    """Render label/value pairs as an aligned monospace block.

    A plain ``` fence rather than ```ansi: ANSI colour renders on desktop but
    degrades to visible escape codes on older/mobile clients, and the embed's
    colour bar already carries win/loss. Alignment is what buys readability
    here; colour is a bonus we don't need to risk.
    """
    label_w = max((len(label) for label, _ in rows if label != "-"), default=0)
    rendered = [
        (label, f"{label:<{label_w}}  {value}".rstrip())
        for label, value in rows
    ]
    # Rule spans the widest actual line, so it reads as a rule and not a dash.
    rule = "─" * max((len(line) for label, line in rendered if label != "-"), default=0)
    body = "\n".join(rule if label == "-" else line for label, line in rendered)
    return f"```\n{body}\n```"


def _embed(title: str, color: int, rows: list, strategy_name: Optional[str]) -> Dict[str, Any]:
    embed: Dict[str, Any] = {
        "title": title,
        "color": color,
        "description": _table(rows),
    }
    if strategy_name:
        embed["footer"] = {"text": strategy_name}
    return embed


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

    multiplier = _contract_multiplier(option_symbol, symbol)
    cost = price * qty * multiplier
    unit = "contract" if multiplier == 100 else "share"

    rows = [
        ("Qty", f"{qty} {unit}{'s' if qty != 1 else ''}"),
        ("Premium", f"${price:.2f}"),
        ("-", ""),
        # The number that actually left the account.
        ("Cost", _money(cost)),
    ]

    _post_async(
        webhook,
        {"embeds": [_embed(
            f"🟢  Opened · {format_contract(option_symbol, symbol)}",
            _COLOR_GREEN, rows, strategy_name,
        )]},
    )


def notify_position_closed(
    user_prefs: Optional[Dict[str, Any]],
    symbol: str,
    qty: int,
    price: float,
    pnl: float,
    strategy_name: Optional[str] = None,
    option_symbol: Optional[str] = None,
    entry_price: Optional[float] = None,
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
    emoji = "🟢" if is_win else "🔴"

    multiplier = _contract_multiplier(option_symbol, symbol)
    proceeds = price * qty * multiplier
    unit = "contract" if multiplier == 100 else "share"

    # Premium vs. dollars, side by side. `price` is the per-share premium
    # ($2.23); the money that moved is that times qty times the 100-share
    # contract multiplier ($223). Showing only the premium made every P&L
    # impossible to read as exposure.
    rows = [("Qty", f"{qty} {unit}{'s' if qty != 1 else ''}")]
    if entry_price:
        cost = entry_price * qty * multiplier
        rows += [
            ("Entry", f"${entry_price:.2f}   →   {_money(cost)}"),
            ("Exit", f"${price:.2f}   →   {_money(proceeds)}"),
            ("-", ""),
            ("P&L", _signed_money(pnl)),
        ]
        if cost > 0.01:
            rows.append(("Return", f"{pnl / cost * 100:+.1f}%"))
    else:
        rows += [
            ("Exit", f"${price:.2f}   →   {_money(proceeds)}"),
            ("-", ""),
            ("P&L", _signed_money(pnl)),
        ]

    _post_async(
        webhook,
        {"embeds": [_embed(
            f"{emoji}  Closed · {format_contract(option_symbol, symbol)}",
            color, rows, strategy_name,
        )]},
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
