"""Tests for the AI-ban store pieces and the moderation log
(2026-10-25 anti-abuse round): AI bans are separate from global bans,
the log records actor/action/target, and the per-actor daily count
behind the non-owner global-ban limit works.
Run: python3 test_aiban.py"""
import os, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_tmp = tempfile.mkdtemp()
os.environ["DB_PATH"] = os.path.join(_tmp, "test.db")

import store

fails = []
def check(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    if not cond: fails.append(name)

# --- AI bans ---
check("not AI-banned by default", not store.is_ai_banned(777))
store.ai_ban_add(777, "prompt spam", 42)
check("AI ban stored", store.is_ai_banned(777))
row = store.ai_ban_get(777)
check("AI ban keeps reason + banner", row["reason"] == "prompt spam" and row["banned_by"] == 42)
check("AI ban list has 1", len(store.ai_ban_all()) == 1)
store.ai_ban_add(777, "updated reason", 43)
check("AI ban upsert keeps 1 row", len(store.ai_ban_all()) == 1 and store.ai_ban_get(777)["reason"] == "updated reason")
check("AI ban is NOT a global ban", store.gban_get(777) is None)
check("AI ban remove works", store.ai_ban_remove(777) == 1)
check("AI ban gone", not store.is_ai_banned(777))
check("AI ban remove again no-op", store.ai_ban_remove(777) == 0)

# --- Moderation log ---
store.mod_log_add(42, "gban", 777, -1001, "phishing")
store.mod_log_add(42, "gban", 778, -1001, "spam")
store.mod_log_add(43, "gban", 779, -1001, "spam")
store.mod_log_add(42, "aiban", 780, -1001, "prompt spam")
rows = store.mod_log_recent(10)
check("log has 4 rows", len(rows) == 4)
check("log is latest-first", rows[0]["action"] == "aiban" and rows[0]["target"] == 780)
check("log keeps actor + detail", rows[3]["actor"] == 42 and rows[3]["detail"] == "phishing")
check("count: actor 42 has 2 gbans", store.mod_action_count(42, "gban", 0) == 2)
check("count: actor 43 has 1 gban", store.mod_action_count(43, "gban", 0) == 1)
check("count: aiban counted separately", store.mod_action_count(42, "aiban", 0) == 1)
check("count: future cutoff counts 0", store.mod_action_count(42, "gban", 9999999999) == 0)
check("log limit respected", len(store.mod_log_recent(2)) == 2)

# --- Stats include AI bans ---
store.ai_ban_add(888, "x", 42)
s = store.mod_stats()
check("stats count AI bans", s["ai_bans"] == 1)

print()
print("FAILURES:", fails if fails else "none")
sys.exit(1 if fails else 0)
