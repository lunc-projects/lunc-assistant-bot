"""Unit tests for ratelimit.py — no network, no Telegram, no database."""

import ratelimit

OWNER = 999


def fresh():
    ratelimit.reset()


def test_user_cap():
    fresh()
    for _ in range(ratelimit.USER_PER_HOUR):
        assert ratelimit.allowed(1, -100, OWNER) is True
    assert ratelimit.allowed(1, -100, OWNER) is False


def test_blocked_call_consumes_nothing():
    fresh()
    for _ in range(ratelimit.USER_PER_HOUR):
        ratelimit.allowed(1, -100, OWNER, now=1000)
    assert ratelimit.allowed(1, -100, OWNER, now=1000) is False
    # Still blocked (count unchanged), then allowed once the window passes.
    assert ratelimit.allowed(1, -100, OWNER, now=1000) is False
    assert ratelimit.allowed(1, -100, OWNER, now=1000 + 3601) is True


def test_owner_exempt():
    fresh()
    for _ in range(ratelimit.USER_PER_HOUR + 50):
        assert ratelimit.allowed(OWNER, -100, OWNER) is True


def test_users_independent():
    fresh()
    for _ in range(ratelimit.USER_PER_HOUR):
        ratelimit.allowed(1, -100, OWNER)
    assert ratelimit.allowed(1, -100, OWNER) is False
    assert ratelimit.allowed(2, -100, OWNER) is True


def test_chat_cap():
    fresh()
    for u in range(ratelimit.CHAT_PER_HOUR):
        assert ratelimit.allowed(1000 + u, -100, OWNER) is True
    assert ratelimit.allowed(9999, -100, OWNER) is False
    # A different chat is unaffected.
    assert ratelimit.allowed(9999, -200, OWNER) is True


def test_window_expiry():
    fresh()
    assert ratelimit.allowed(1, -100, OWNER, now=1000) is True
    # 3600s later the old call has expired: a fresh call fits again even
    # after filling the cap at the old timestamp.
    for _ in range(ratelimit.USER_PER_HOUR - 1):
        ratelimit.allowed(1, -100, OWNER, now=1000)
    assert ratelimit.allowed(1, -100, OWNER, now=1000) is False
    assert ratelimit.allowed(1, -100, OWNER, now=1000 + 3601) is True


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"PASS {name}")
    print("ratelimit: all tests passed")
