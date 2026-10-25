"""Tests for Phase 2 moderation store pieces: word blacklist, scam-alert
settings, and the protection stats rollup. Run: python3 test_phase2.py"""
import os, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_tmp = tempfile.mkdtemp()
os.environ["DB_PATH"] = os.path.join(_tmp, "test.db")

import store

fails = []
def check(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    if not cond: fails.append(name)

# --- Blacklist ---
check("blacklist starts empty", store.blacklist_all() == [])
store.blacklist_add("freelunc", 42)
store.blacklist_add("airdropclaim", 42)
store.blacklist_add("freelunc", 43)  # duplicate is a no-op
words = store.blacklist_all()
check("two words stored, sorted", words == ["airdropclaim", "freelunc"])
check("remove works", store.blacklist_remove("freelunc") == 1)
check("list shrinks", store.blacklist_all() == ["airdropclaim"])
check("remove again is a no-op", store.blacklist_remove("freelunc") == 0)

# --- Scam alert settings ---
check("alerts off by default", not store.scam_alerts_enabled(-1001))
store.set_scam_alerts(-1001, True)
check("alerts on after set", store.scam_alerts_enabled(-1001))
check("per-group: other group still off", not store.scam_alerts_enabled(-2002))
store.set_scam_alerts(-1001, False)
check("alerts off after unset", not store.scam_alerts_enabled(-1001))
check("last-sent starts at 0", store.scam_last(-1001) == 0)
store.set_scam_last(-1001, 1234567)
check("last-sent roundtrip", store.scam_last(-1001) == 1234567)

# --- Stats rollup ---
store.mod_request_group(-1001, "Group One", 42)
store.mod_request_group(-2002, "Group Two", 42)
store.mod_approve_group(-1001)
store.gban_add(777, "spam", 42)
store.gban_add(778, "phish", 42)
store.elevated_add(555, 42)
store.member_verify(-1001, 888)
store.member_verify(-1001, 889)
store.captcha_start(-1001, 999, 9999999999)
s = store.mod_stats()
check("stats: 1 protected", s["groups_protected"] == 1)
check("stats: 1 pending", s["groups_pending"] == 1)
check("stats: 2 gbans", s["gbans"] == 2)
check("stats: 1 elevated", s["elevated"] == 1)
check("stats: 2 verified", s["verified"] == 2)
check("stats: 1 waiting on captcha", s["pending"] == 1)

print()
print("FAILURES:", fails if fails else "none")
sys.exit(1 if fails else 0)
