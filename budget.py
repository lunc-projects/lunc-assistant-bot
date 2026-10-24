"""Daily AI token pot — the bot's share of the owner's Groq free allowance.

Why this exists: the Groq free plan gives 200,000 tokens per day for
gpt-oss-120b, resetting at UTC midnight. Without a pot, one busy group
could burn the whole day's allowance and every later AI call would hit
Groq's 429 wall. The pot makes the bot stop gracefully instead: when the
day's estimated spend hits the cap, AI answers pause with a "daily limit
reached" note, and the bot keeps working (simple commands + basic non-AI
summaries) until new tokens come at midnight UTC.

Rules:
- DAILY_TOKEN_BUDGET = 200,000 estimated tokens per UTC day — the full
  free-plan allowance for gpt-oss-120b. The owner picked the full amount:
  use the pot, then stop.
- Estimates, not metered billing: input tokens are approximated as
  chars // 4, output is reserved at the call's max_tokens and settled to
  the real reply length afterwards. Tokenizers differ from chars // 4,
  so Groq's own daily cap stays the hard backstop; the pot's job is to
  stop gracefully before that wall, not to meter Groq exactly.
- Applies to everyone including the owner: the pot is the pot.
- In-memory only: a redeploy resets the counter, which is fine — Groq's
  own hard cap is the backstop, and the pot is a graceful-stop guard.
- A blocked call consumes nothing and is never recorded.
- A failed call (network error, Groq 429) is refunded: no tokens were
  spent, so the pot does not pay for it.
"""

import datetime

DAILY_TOKEN_BUDGET = 200_000

_spent = 0
_day = None


def _today(today=None):
    if today is not None:
        return today
    return datetime.datetime.now(datetime.timezone.utc).date()


def _rollover(day):
    global _spent, _day
    if _day != day:
        _day = day
        _spent = 0


def estimate_input(messages):
    """Rough input tokens for a chat-completions message list."""
    return sum(len(m.get("content", "")) for m in messages) // 4


def spent(today=None):
    _rollover(_today(today))
    return _spent


def remaining(today=None):
    return DAILY_TOKEN_BUDGET - spent(today)


def exhausted(today=None):
    return spent(today) >= DAILY_TOKEN_BUDGET


def reserve(estimate, today=None):
    """True if estimate fits the day's pot; records it when allowed.

    A blocked reservation consumes nothing.
    """
    global _spent
    day = _today(today)
    _rollover(day)
    if _spent + estimate > DAILY_TOKEN_BUDGET:
        return False
    _spent += estimate
    return True


def refund(amount, today=None):
    """Give back unspent reservation (failed call, output shorter than max)."""
    global _spent
    day = _today(today)
    _rollover(day)
    _spent = max(0, _spent - amount)


def reset():
    global _spent, _day
    _spent = 0
    _day = None
