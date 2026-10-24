"""Hourly caps on AI calls — protects the bot's Groq quota from spam.

Why this exists: anyone who can reach the bot (a group member, or any
Telegram user via DM) can trigger an AI call, and every call spends the
owner's Groq tokens. Without a cap, one person hammering /ask, mentions,
or long DM pastes could burn the whole daily allowance.

Rules:
- Per user: 20 AI calls per rolling hour.
- Per chat: 100 AI calls per rolling hour (so one busy group can't hog
  the quota either).
- The owner (OWNER_TELEGRAM_ID) is exempt.
- In-memory only: a redeploy resets the counters, which is fine for
  rate limiting and matches this bot's ephemeral design.
- A blocked call consumes nothing and is never recorded.
"""

import time
from collections import deque

USER_PER_HOUR = 20
CHAT_PER_HOUR = 100
WINDOW = 3600

# Hourly caps by rank: (per-user, per-chat). Rank 0 never reaches this
# function — the rank gate in ai_guard blocks rank 0 before any cap check.
RANK_CAPS = {1: (20, 100), 2: (50, 200)}

_user_calls: dict[int, deque] = {}
_chat_calls: dict[int, deque] = {}


def _prune(q, now):
    while q and q[0] <= now - WINDOW:
        q.popleft()


def allowed_for_rank(user_id, chat_id, owner_id=0, rank=1, now=None):
    """True if this AI call fits the rank's caps; records the call when allowed.

    Synchronous on purpose: check + record happen with no await between
    them, so two concurrent handlers can't both slip past the cap.
    """
    if owner_id and user_id == owner_id:
        return True
    now = time.time() if now is None else now
    user_cap, chat_cap = RANK_CAPS.get(rank, RANK_CAPS[1])
    uq = _user_calls.setdefault(user_id, deque())
    cq = _chat_calls.setdefault(chat_id, deque())
    _prune(uq, now)
    _prune(cq, now)
    if len(uq) >= user_cap or len(cq) >= chat_cap:
        return False
    uq.append(now)
    cq.append(now)
    return True


def allowed(user_id, chat_id, owner_id=0, now=None):
    """Rank-1 caps (kept for callers that don't know the rank)."""
    return allowed_for_rank(user_id, chat_id, owner_id, rank=1, now=now)


def reset():
    _user_calls.clear()
    _chat_calls.clear()
