"""Unit tests for budget.py — no network, no Telegram, no database."""

import datetime

import budget

DAY1 = datetime.date(2026, 10, 24)
DAY2 = datetime.date(2026, 10, 25)


def fresh():
    budget.reset()


def test_estimate_input():
    fresh()
    assert budget.estimate_input([{"role": "system", "content": "abcd"},
                                  {"role": "user", "content": "efgh"}]) == 2
    assert budget.estimate_input([]) == 0


def test_reserve_within_budget():
    fresh()
    assert budget.reserve(100_000, today=DAY1) is True
    assert budget.spent(today=DAY1) == 100_000
    assert budget.remaining(today=DAY1) == 100_000
    assert budget.exhausted(today=DAY1) is False


def test_reserve_over_budget_consumes_nothing():
    fresh()
    assert budget.reserve(199_000, today=DAY1) is True
    assert budget.reserve(2_000, today=DAY1) is False
    assert budget.spent(today=DAY1) == 199_000
    # A fitting call still works after a blocked one.
    assert budget.reserve(1_000, today=DAY1) is True
    assert budget.spent(today=DAY1) == 200_000


def test_exhausted_boundary():
    fresh()
    assert budget.reserve(budget.DAILY_TOKEN_BUDGET, today=DAY1) is True
    assert budget.exhausted(today=DAY1) is True
    assert budget.reserve(1, today=DAY1) is False


def test_refund():
    fresh()
    assert budget.reserve(10_000, today=DAY1) is True
    budget.refund(4_000, today=DAY1)
    assert budget.spent(today=DAY1) == 6_000
    # Refunds never drive the pot below zero.
    budget.refund(99_000, today=DAY1)
    assert budget.spent(today=DAY1) == 0


def test_day_rollover():
    fresh()
    assert budget.reserve(150_000, today=DAY1) is True
    assert budget.spent(today=DAY1) == 150_000
    # A new UTC day starts with a fresh pot.
    assert budget.spent(today=DAY2) == 0
    assert budget.exhausted(today=DAY2) is False
    assert budget.reserve(150_000, today=DAY2) is True


def test_full_allowance_is_the_cap():
    fresh()
    assert budget.DAILY_TOKEN_BUDGET == 200_000


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"PASS {name}")
    print("budget: all tests passed")
