"""Rank tests for the LUNC Assistant Bot: earned days, thresholds, manual
override, DM (anywhere) rank, and rank-aware daily caps.

Runs against a temp SQLite DB (DB_PATH env set before importing store).
"""
import os
import sqlite3
import sys
import tempfile

tmp = tempfile.mkdtemp()
os.environ["DB_PATH"] = os.path.join(tmp, "test.db")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import store
import ratelimit

passed = 0
failed = 0


def check(cond, msg):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ok: {msg}")
    else:
        failed += 1
        print(f"  FAIL: {msg}")


print("== earned rank days ==")
store.log_message(-100, 7, "Tester", "hello", 1)
store.log_message(-100, 7, "Tester", "again", 2)
check(store.days_active(-100, 7) == 1, "two messages same day = 1 rank day")
check(store.rank_for(-100, 7) == 0, "1 day active = rank 0")
check(store.rank_for(-100, 999) == 0, "never seen = rank 0")

# Simulate 3 distinct past days directly (log_message stamps 'today' only).
c = sqlite3.connect(os.environ["DB_PATH"])
for d in ("2026-10-20", "2026-10-21", "2026-10-22"):
    c.execute("INSERT OR IGNORE INTO rank_days VALUES(-100, 7, ?)", (d,))
c.commit()
c.close()
check(store.days_active(-100, 7) >= 3, "past days accumulate")
check(store.rank_for(-100, 7) == 1, "3+ days active = rank 1")
check(store.rank_anywhere(7) == 1, "anywhere rank follows days across chats")

print("== manual override ==")
store.set_rank_override(-100, 7, 2, 1)
check(store.rank_for(-100, 7) == 2, "manual override to 2 wins over earned rank")
rank, days, override = store.rank_info(-100, 7)
check(override == 2, "rank_info reports the override")
store.set_rank_override(-100, 7, 0, 1)
check(store.rank_for(-100, 7) == 0, "manual override to 0 demotes")
check(store.clear_rank_override(-100, 7) == 1, "clear removes one override")
check(store.rank_for(-100, 7) == 1, "clearing override restores earned rank")
check(store.clear_rank_override(-100, 7) == 0, "clearing again removes nothing")
try:
    store.set_rank_override(-100, 7, 5, 1)
    check(False, "rank 5 rejected")
except ValueError:
    check(True, "rank 5 rejected")

print("== rank thresholds ==")
check(store._rank_from_days(0) == 0, "0 days = rank 0")
check(store._rank_from_days(2) == 0, "2 days = rank 0")
check(store._rank_from_days(3) == 1, "3 days = rank 1")
check(store._rank_from_days(29) == 1, "29 days = rank 1")
check(store._rank_from_days(30) == 2, "30 days = rank 2")

print("== rank-aware caps ==")
ratelimit.reset()
ok = all(ratelimit.allowed_for_rank(5, -100, 0, rank=0, now=1000.0 + i) for i in range(2))
check(ok, "rank 0 (starting) allows 2/day")
check(not ratelimit.allowed_for_rank(5, -100, 0, rank=0, now=1000.0 + 3),
      "rank 0 blocks 3rd/day")
ratelimit.reset()
ok = all(ratelimit.allowed_for_rank(5, -100, 0, rank=1, now=1000.0 + i) for i in range(4))
check(ok, "rank 1 allows 4/day")
check(not ratelimit.allowed_for_rank(5, -100, 0, rank=1, now=1000.0 + 5),
      "rank 1 blocks 5th/day")
ratelimit.reset()
ok = all(ratelimit.allowed_for_rank(5, -100, 0, rank=2, now=1000.0 + i) for i in range(6))
check(ok, "rank 2 allows 6/day")
check(not ratelimit.allowed_for_rank(5, -100, 0, rank=2, now=1000.0 + 7),
      "rank 2 blocks 7th/day")
ratelimit.reset()
check(ratelimit.allowed(5, -100, 0, now=2000.0), "legacy allowed() still works (rank 1 caps)")
ratelimit.reset()
check(all(ratelimit.allowed_for_rank(999, -100, 999, rank=0, now=3000.0 + i) for i in range(5)),
      "owner exempt from caps regardless of rank")

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
