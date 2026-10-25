"""Unit tests for ratelimit.py — no network, no Telegram, no database.

Caps are per UTC day (owner decision 2026-10-25: daily, not hourly).
Timestamps: 1000.0 = 1970-01-01 00:16:40 UTC; +86400s = the next UTC day.
"""

import ratelimit

OWNER = 999
DAY1 = 1000.0
DAY2 = DAY1 + 86400


def fresh():
    ratelimit.reset()


def test_user_cap():
    fresh()
    for _ in range(ratelimit.USER_PER_DAY):
        assert ratelimit.allowed(1, -100, OWNER, now=DAY1) is True
    assert ratelimit.allowed(1, -100, OWNER, now=DAY1) is False


def test_blocked_call_consumes_nothing():
    fresh()
    for _ in range(ratelimit.USER_PER_DAY):
        ratelimit.allowed(1, -100, OWNER, now=DAY1)
    assert ratelimit.allowed(1, -100, OWNER, now=DAY1) is False
    # Still blocked later the SAME day (count unchanged)...
    assert ratelimit.allowed(1, -100, OWNER, now=DAY1 + 3600) is False
    # ...and allowed again on the next UTC day.
    assert ratelimit.allowed(1, -100, OWNER, now=DAY2) is True


def test_owner_exempt():
    fresh()
    for _ in range(ratelimit.USER_PER_DAY + 50):
        assert ratelimit.allowed(OWNER, -100, OWNER, now=DAY1) is True


def test_users_independent():
    fresh()
    for _ in range(ratelimit.USER_PER_DAY):
        ratelimit.allowed(1, -100, OWNER, now=DAY1)
    assert ratelimit.allowed(1, -100, OWNER, now=DAY1) is False
    assert ratelimit.allowed(2, -100, OWNER, now=DAY1) is True


def test_chat_cap():
    fresh()
    for u in range(ratelimit.CHAT_PER_DAY):
        assert ratelimit.allowed(1000 + u, -100, OWNER, now=DAY1) is True
    assert ratelimit.allowed(9999, -100, OWNER, now=DAY1) is False
    # A different chat is unaffected.
    assert ratelimit.allowed(9999, -200, OWNER, now=DAY1) is True
    # The capped chat resets on the next UTC day.
    assert ratelimit.allowed(9999, -100, OWNER, now=DAY2) is True


def test_rank_caps():
    fresh()
    for _ in range(6):
        assert ratelimit.allowed_for_rank(7, -300, OWNER, rank=2, now=DAY1) is True
    assert ratelimit.allowed_for_rank(7, -300, OWNER, rank=2, now=DAY1) is False
    assert ratelimit.allowed_for_rank(7, -300, OWNER, rank=2, now=DAY2) is True


def test_rank_zero_and_one_caps():
    fresh()
    for _ in range(2):
        assert ratelimit.allowed_for_rank(8, -400, OWNER, rank=0, now=DAY1) is True
    assert ratelimit.allowed_for_rank(8, -400, OWNER, rank=0, now=DAY1) is False
    fresh()
    for _ in range(4):
        assert ratelimit.allowed_for_rank(9, -500, OWNER, rank=1, now=DAY1) is True
    assert ratelimit.allowed_for_rank(9, -500, OWNER, rank=1, now=DAY1) is False


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"PASS {name}")
    print("ratelimit: all tests passed")
