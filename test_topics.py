"""Tests for the Lunetta-style hashtag topics and per-group rules/welcome
settings. Run: python3 test_topics.py"""
import os, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_tmp = tempfile.mkdtemp()
os.environ["DB_PATH"] = os.path.join(_tmp, "test.db")

import store, topics

fails = []
def check(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    if not cond: fails.append(name)

# --- Lookup: canonical + aliases + case ---
check("canonical #memo resolves", topics.lookup("memo") is not None and "MEMO" in topics.lookup("memo"))
check("case-insensitive", topics.lookup("MEMO") == topics.lookup("memo"))
check("alias #scamwarning -> safety", topics.lookup("scamwarning") == topics.lookup("safety"))
check("alias #transporterror -> commonissues", topics.lookup("transporterror") == topics.lookup("commonissues"))
check("alias #buyluna -> tokenomics", topics.lookup("buyluna") == topics.lookup("tokenomics"))
check("unknown tag -> None", topics.lookup("nosuchtag") is None)
check("known() covers dynamic tags", topics.known("rules") and topics.known("welcome") and topics.known("commands"))
check("known() covers aliases", topics.known("nodm"))
check("known() rejects junk", not topics.known("whatever123"))

# --- Content hygiene: no placeholders, sane length, no truncated junk ---
bad = []
for tag, text in topics.TOPICS.items():
    if "add later" in text or "TODO" in text or len(text) < 40 or len(text) > 1000:
        bad.append(tag)
check("all topic texts are complete and sized sanely", not bad)

# --- Commands list ---
ct = topics.commands_text()
check("#commands lists the tags", "#memo" in ct and "#scammed" in ct and "#rules" in ct)

# --- Group rules / welcome settings roundtrip ---
check("rules unset by default", store.get_setting(-1001, "rules_text") is None)
store.set_setting(-1001, "rules_text", "Be kind. No spam.")
check("rules roundtrip", store.get_setting(-1001, "rules_text") == "Be kind. No spam.")
check("rules are per-group", store.get_setting(-2002, "rules_text") is None)
store.set_setting(-1001, "welcome_text", "Say hi!")
check("welcome roundtrip", store.get_setting(-1001, "welcome_text") == "Say hi!")

print()
print("FAILURES:", fails if fails else "none")
sys.exit(1 if fails else 0)
