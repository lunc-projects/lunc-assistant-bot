"""Tests for the final fixes round (2026-10-25): edit link-swap logic
(seclogic), captcha strikes + message_text lookup (store).
Run: python3 test_fixes3.py"""
import os, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_tmp = tempfile.mkdtemp()
os.environ["DB_PATH"] = os.path.join(_tmp, "test.db")

import seclogic
import store

fails = []
def check(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    if not cond: fails.append(name)

# --- has_link / edit_adds_link ---
check("has_link on URL", seclogic.has_link("go to https://example.com/x") is True)
check("has_link on bare domain", seclogic.has_link("visit luncscan.com today") is True)
check("has_link on t.me", seclogic.has_link("join t.me/somechannel") is True)
check("has_link on plain text", seclogic.has_link("just a normal message") is False)
check("edit adding a link = swap",
      seclogic.edit_adds_link("gm everyone, nice day", "gm everyone https://scam.example/claim") is True)
check("edit keeping a link = not a swap",
      seclogic.edit_adds_link("see https://luncscan.com", "see https://luncscan.com (fixed)") is False)
check("edit without links = not a swap",
      seclogic.edit_adds_link("hello world", "hello world, edited") is False)
check("edit removing a link = not a swap",
      seclogic.edit_adds_link("bad https://scam.example", "sorry wrong chat") is False)
check("unknown original = not a swap (no guessing)",
      seclogic.edit_adds_link(None, "https://anything.example") is False)

# --- captcha strikes ---
check("first strike = 1", store.captcha_strike_add(-1001, 777) == 1)
check("second strike = 2", store.captcha_strike_add(-1001, 777) == 2)
check("third strike = 3", store.captcha_strike_add(-1001, 777) == 3)
check("strikes are per chat", store.captcha_strike_add(-1002, 777) == 1)
store.captcha_strikes_clear(-1001, 777)
check("cleared strikes restart at 1", store.captcha_strike_add(-1001, 777) == 1)

# --- message_text lookup (edit comparison source) ---
store.log_message(-1001, 777, "Tester", "original clean text", 4242)
check("message_text returns the logged original",
      store.message_text(-1001, 4242) == "original clean text")
check("message_text unknown id -> None", store.message_text(-1001, 9999) is None)
check("message_text wrong chat -> None", store.message_text(-1002, 4242) is None)

print()
print("FAILURES:", fails if fails else "none")
sys.exit(1 if fails else 0)
