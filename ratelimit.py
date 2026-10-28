"""Daily caps on AI calls — protects the bot's Groq quota from spam.

Why this exists: anyone who can reach the bot (a group member, or any
Telegram user via DM) can trigger an AI call, and every call spends the
owner's Groq tokens. These caps bound how much any one user — or one
busy group — can spend in a day.

Rules (owner decision 2026-10-27, replacing the 2026-10-25 rank ladder
of 2/4/6 so the free daily pot lasts longer):
- Per user per UTC day: ONE AI call for everyone, whatever their rank.
  Ranks still exist — earned by chatting on distinct days — and still
  set the per-chat allowance below, but they no longer raise the
  personal limit.
- One exception: a manual rank override is an explicit per-user
  decision by the owner (/rankset), so it still wins over the flat 1 —
  an overridden user's personal cap follows the old ladder for the
  rank the owner set (rank 0 = 2, rank 1 = 4, rank 2 = 6).
- Per chat per UTC day, by the caller's rank: rank 0 = 10, rank 1 = 20,
  rank 2 = 30 (unchanged).
- "Day" is the UTC calendar day — the same reset as the daily token
  pot (budget.py) and Groq's own quota: counters reset at midnight UTC.
- The owner (OWNER_TELEGRAM_ID) is exempt.
- In-memory only: a redeploy resets the counters, which is fine for
  rate limiting and matches this bot's ephemeral design.
- A blocked call consumes nothing and is never recorded.
"""

import time
from datetime import datetime, timezone

USER_PER_DAY = 1
CHAT_PER_DAY = 20

# Per-chat daily caps by the caller's rank.
CHAT_CAPS = {0: 10, 1: 20, 2: 30}
# Personal daily caps ONLY for users whose rank the owner set manually
# (/rankset override): the explicit owner decision wins over the flat 1.
OVERRIDE_USER_CAPS = {0: 2, 1: 4, 2: 6}

_user_counts: dict[int, list] = {}  # user_id -> [utc_day, count]
_chat_counts: dict[int, list] = {}  # chat_id -> [utc_day, count]


def _utc_day(now):
    return datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%d")


def _count(store, key, day):
    entry = store.get(key)
    return entry[1] if entry is not None and entry[0] == day else 0


def _bump(store, key, day):
    entry = store.get(key)
    if entry is None or entry[0] != day:
        store[key] = [day, 1]
    else:
        entry[1] += 1


def allowed_for_rank(user_id, chat_id, owner_id=0, rank=1, now=None, overridden=False):
    """True if this AI call fits the daily caps; records it when allowed.

    Personal cap: 1/day for everyone, unless `overridden` — the caller
    passes True when the rank came from the owner's manual /rankset, in
    which case the old ladder for that rank applies (2/4/6). Chat cap:
    10/20/30 by rank, as before.

    Synchronous on purpose: check + record happen with no await between
    them, so two concurrent handlers can't both slip past the cap.
    """
    if owner_id and user_id == owner_id:
        return True
    now = time.time() if now is None else now
    day = _utc_day(now)
    if overridden:
        user_cap = OVERRIDE_USER_CAPS.get(rank, OVERRIDE_USER_CAPS[0])
    else:
        user_cap = USER_PER_DAY
    chat_cap = CHAT_CAPS.get(rank, CHAT_CAPS[0])
    if _count(_user_counts, user_id, day) >= user_cap:
        return False
    if _count(_chat_counts, chat_id, day) >= chat_cap:
        return False
    _bump(_user_counts, user_id, day)
    _bump(_chat_counts, chat_id, day)
    return True


def allowed(user_id, chat_id, owner_id=0, now=None):
    """Flat personal cap + rank-1 chat cap (callers that don't know the rank)."""
    return allowed_for_rank(user_id, chat_id, owner_id, rank=1, now=now)


def reset():
    _user_counts.clear()
    _chat_counts.clear()
