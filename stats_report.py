"""Cross-bot daily usage stats — publish + read side (LUNC Assistant).

Steve's ruling (2026-10-27): the four assistant bots' usage counts
come together as ONE daily report, not four separate ones. Each bot
publishes its own counts to a shared Upstash DB under
``botstats:<name>``; this bot (LUNC Assistant) is the aggregator that
reads the other three back at report time.

Counts ONLY — this module never touches names, titles, usernames or
message text; payloads are plain numbers plus a unix timestamp.

Config is env-only: UPSTASH_STATS_URL + UPSTASH_STATS_TOKEN. When
either is unset the module is a silent no-op (publish returns False,
reads return None) so the bots run exactly as before until the shared
DB is wired up. Every network call is wrapped so a stats failure can
never break the bot.
"""
import datetime as _dt
import json
import os
import time
from urllib.parse import quote

import httpx

BOT_NAME = "lunc"
KEY_PREFIX = "botstats:"
KEY = KEY_PREFIX + BOT_NAME
TTL_SECONDS = 3 * 24 * 3600          # a report key lives 3 days
STALE_SECONDS = 26 * 3600            # older than this = "no fresh report"

try:
    from zoneinfo import ZoneInfo as _ZoneInfo
    _ET = _ZoneInfo("America/New_York")
except Exception:  # pragma: no cover - zoneinfo always present on py3.9+
    _ET = _dt.timezone(_dt.timedelta(hours=-5))


def configured():
    return bool(os.getenv("UPSTASH_STATS_URL") and os.getenv("UPSTASH_STATS_TOKEN"))


def _base():
    return (os.getenv("UPSTASH_STATS_URL") or "").rstrip("/")


def _headers():
    return {"Authorization": f"Bearer {os.getenv('UPSTASH_STATS_TOKEN') or ''}"}


def current_counts():
    """This bot's counts, from the same sources /botstats uses:
    store.registry_counts() (the persistent usage registry) plus the
    old log-based store.usage_counts() and the AI pot (budget)."""
    import budget
    import store
    c = store.registry_counts()
    legacy = store.usage_counts()
    i = c["interactions_today"]
    return {
        "day": c["day"],
        "groups_member": c["groups_member"],
        "groups_unknown": c["groups_unknown"],
        "groups_left": c["groups_left"],
        "groups_active_today": c["groups_active_today"],
        "new_groups_today": c["new_groups_today"],
        "people_total": c["people_total"],
        "people_dm_total": c["people_dm_total"],
        "people_group_total": c["people_group_total"],
        "people_active_today": c["people_active_today"],
        "dm_active_today": c["dm_active_today"],
        "new_people_today": c["new_people_today"],
        "interactions_total": c["interactions_total"],
        "interactions_command": i["command"],
        "interactions_message": i["message"],
        "interactions_button": i["button"],
        "interactions_other": i["other"],
        "messages_logged": c["messages_logged"],
        "pot_spent": budget.spent(),
        "pot_budget": budget.DAILY_TOKEN_BUDGET,
        "legacy_groups": legacy["groups"],
        "legacy_people_in_groups": legacy["people_in_groups"],
        "legacy_dm_users": legacy["dm_users"],
    }


def build_payload(counts, ts=None):
    payload = {"bot": BOT_NAME, "ts": int(ts if ts is not None else time.time())}
    payload.update(counts)
    return payload


async def publish(counts=None, client_factory=None):
    """Write this bot's counts to the shared DB. Returns True on
    success; False (silently) when unconfigured or on any failure."""
    try:
        if not configured():
            return False
        if counts is None:
            counts = current_counts()
        factory = client_factory or (lambda: httpx.AsyncClient(timeout=15))
        async with factory() as client:
            r = await client.post(
                f"{_base()}/set/{quote(KEY, safe='')}?EX={TTL_SECONDS}",
                headers=_headers(), content=json.dumps(build_payload(counts)))
            r.raise_for_status()
        return True
    except Exception:
        return False


async def read_bot(name, client_factory=None):
    """Read another bot's published counts.

    Returns the payload dict, or None when the key is missing/corrupt.
    RAISES on transport/HTTP failure — the aggregator treats that as
    "reads failed entirely" and falls back to the solo report."""
    if not configured():
        return None
    factory = client_factory or (lambda: httpx.AsyncClient(timeout=15))
    async with factory() as client:
        r = await client.get(
            f"{_base()}/get/{quote(KEY_PREFIX + name, safe='')}",
            headers=_headers())
        r.raise_for_status()
        result = r.json().get("result")
    if not result:
        return None
    try:
        data = json.loads(result)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def is_fresh(payload, now=None):
    if not payload:
        return False
    try:
        ts = int(payload.get("ts") or 0)
    except (TypeError, ValueError):
        return False
    return ts > 0 and (int(now if now is not None else time.time()) - ts) <= STALE_SECONDS


def fmt_ts_et(ts):
    """'2026-10-27 19:02 ET' for a unix timestamp; 'never' for none."""
    if not ts:
        return "never"
    return _dt.datetime.fromtimestamp(int(ts), _ET).strftime("%Y-%m-%d %H:%M ET")
