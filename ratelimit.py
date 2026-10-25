"""Daily caps on AI calls — protects the bot's Groq quota from spam.

Why this exists: anyone who can reach the bot (a group member, or any
Telegram user via DM) can trigger an AI call, and every call spends the
owner's Groq tokens. These caps bound how much any one user — or one
busy group — can spend in a day.

Rules (owner decision 2026-10-25, tightened the same day: "two
questions per day to start, four then six"):
- Per user per UTC day: rank 0 (starting) = 2 AI calls, rank 1 = 4,
  rank 2 = 6. Rank is earned by chatting on distinct days, so the
  allowance grows with time in the community.
- Per chat per UTC day: rank 0 = 10, rank 1 = 20, rank 2 = 30.
- "Day" is the UTC calendar day — the same reset as the daily token
  pot (budget.py) and Groq's own quota: counters reset at midnight UTC.
- The owner (OWNER_TELEGRAM_ID) is exempt.
- In-memory only: a redeploy resets the counters, which is fine for
  rate limiting and matches this bot's ephemeral design.
- A blocked call consumes nothing and is never recorded.
"""

import time
from datetime import datetime, timezone

USER_PER_DAY = 4
CHAT_PER_DAY = 20

# Daily caps by rank: (per-user, per-chat).
RANK_CAPS = {0: (2, 10), 1: (4, 20), 2: (6, 30)}

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


def allowed_for_rank(user_id, chat_id, owner_id=0, rank=1, now=None):
    """True if this AI call fits the rank's daily caps; records it when allowed.

    Synchronous on purpose: check + record happen with no await between
    them, so two concurrent handlers can't both slip past the cap.
    """
    if owner_id and user_id == owner_id:
        return True
    now = time.time() if now is None else now
    day = _utc_day(now)
    user_cap, chat_cap = RANK_CAPS.get(rank, RANK_CAPS[0])
    if _count(_user_counts, user_id, day) >= user_cap:
        return False
    if _count(_chat_counts, chat_id, day) >= chat_cap:
        return False
    _bump(_user_counts, user_id, day)
    _bump(_chat_counts, chat_id, day)
    return True


def allowed(user_id, chat_id, owner_id=0, now=None):
    """Rank-1 caps (kept for callers that don't know the rank)."""
    return allowed_for_rank(user_id, chat_id, owner_id, rank=1, now=now)


def reset():
    _user_counts.clear()
    _chat_counts.clear()
