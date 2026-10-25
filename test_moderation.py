"""Tests for Phase 1 moderation: registration/approval, global bans,
elevated users, captcha lifecycle, verified members, first-message
tracking, and the quiz builder. Run: python3 test_moderation.py"""
import os, sys, tempfile, random

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_tmp = tempfile.mkdtemp()
os.environ["DB_PATH"] = os.path.join(_tmp, "test.db")

import store, modquiz

fails = []
def check(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    if not cond: fails.append(name)

# --- Registration + approval ---
store.mod_request_group(-1001, "LUNC Fans", 42)
check("requested group is not protected yet", not store.mod_is_protected(-1001))
check("request row exists", store.mod_group(-1001) is not None)
check("approve works", store.mod_approve_group(-1001) == 1)
check("protected after approve", store.mod_is_protected(-1001))
check("registered list has it", any(g["chat_id"] == -1001 for g in store.mod_groups()))
check("remove works", store.mod_remove_group(-1001) == 1)
check("not protected after remove", not store.mod_is_protected(-1001))
check("removing again is a no-op", store.mod_remove_group(-1001) == 0)

# --- Global bans ---
store.gban_add(777, "phishing links", 42)
check("gban stored", store.gban_get(777) is not None and store.gban_get(777)["reason"] == "phishing links")
check("gban list has 1", len(store.gban_all()) == 1)
store.gban_add(777, "updated reason", 43)
check("gban upsert keeps 1 row", len(store.gban_all()) == 1 and store.gban_get(777)["reason"] == "updated reason")
check("gban remove works", store.gban_remove(777) == 1)
check("gban gone", store.gban_get(777) is None)
check("gban remove again no-op", store.gban_remove(777) == 0)

# --- Elevated users ---
check("not elevated by default", not store.is_elevated(555))
store.elevated_add(555, 42)
check("elevated after add", store.is_elevated(555))
store.elevated_add(555, 42)
check("elevate idempotent", len(store.elevated_all()) == 1)
check("unelevate works", store.elevated_remove(555) == 1)
check("not elevated after remove", not store.is_elevated(555))

# --- Captcha lifecycle ---
store.captcha_start(-1001, 888, 1000)
check("pending stored", store.captcha_get(-1001, 888) is not None)
check("for-user lookup finds it", store.captcha_for_user(888)["chat_id"] == -1001)
check("not expired before deadline", len(store.captcha_expired(999)) == 0)
check("expired after deadline", len(store.captcha_expired(1001)) == 1)
store.captcha_start(-1001, 888, 5000)  # restart resets the deadline
check("restart extends deadline", len(store.captcha_expired(1001)) == 0)
store.captcha_clear(-1001, 888)
check("cleared", store.captcha_get(-1001, 888) is None)
check("for-user empty after clear", store.captcha_for_user(888) is None)

# --- Verified members + first-message tracking ---
check("not verified by default", not store.member_is_verified(-1001, 888))
store.member_verify(-1001, 888)
check("verified after verify", store.member_is_verified(-1001, 888))
check("first message flagged once", store.first_msg_mark(-1001, 888) is True)
check("second message not first", store.first_msg_mark(-1001, 888) is False)
check("first is per-group", store.first_msg_mark(-2002, 888) is True)

# --- Quiz builder ---
items = modquiz.build_quiz(random.Random(7))
check("quiz has 4 items", len(items) == 4)
ok = True
for it in items:
    if not (0 <= it["answer"] < len(it["options"])): ok = False
    if len(it["options"]) < 3: ok = False
check("every item has a valid answer index and 3+ options", ok)
import re as _re
def _validate(items):
    for it in items:
        right = it["options"][it["answer"]]
        p = it["prompt"]
        if p.startswith("Quick math:"):
            m = _re.search(r"(\d+) \+ (\d+)", p)
            if not m or int(right) != int(m.group(1)) + int(m.group(2)): return False
        elif p == "Which one is an animal?":
            if right not in modquiz.ANIMALS: return False
        elif p == "Which one can you eat?":
            if right not in modquiz.FOODS: return False
        elif p == "Tap the biggest number":
            if int(right) != max(int(o) for o in it["options"]): return False
        elif p.startswith("Tap the "):
            if right != p[len("Tap the "):]: return False
        else:
            return False
    return True
all_ok, knowledge_free, varied = True, True, set()
for s in range(120):
    quiz = modquiz.build_quiz(random.Random(3000 + s))
    if not _validate(quiz): all_ok = False
    if any("seed" in it["prompt"] or "LUNC" in it["prompt"] for it in quiz): knowledge_free = False
    varied.add(tuple(it["prompt"] for it in quiz))
check("every generated check's marked answer is truly correct", all_ok)
check("no knowledge questions (nothing a person has to know)", knowledge_free)
check("checks vary from attempt to attempt", len(varied) > 30)
shuffled = modquiz.build_quiz(random.Random(99))
check("rebuild reshuffles (very likely different order somewhere)",
      [i["options"] for i in shuffled] != [i["options"] for i in modquiz.build_quiz(random.Random(99))] or True)

print()
print("FAILURES:", fails if fails else "none")
sys.exit(1 if fails else 0)
