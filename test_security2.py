"""Tests for security round 2 (2026-10-25): seclogic pure helpers
(link allowlist, message fingerprints, fresh-account test) and the
new store tables (fresh holds, appeals).
Run: python3 test_security2.py"""
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

# --- Link allowlist ---
check("finder link allowed",
      seclogic.all_links_allowlisted("check https://finder.terraclassic.community/mainnet/account/terra1abc"))
check("luncscan bare domain allowed",
      seclogic.all_links_allowlisted("see luncscan.com for staking"))
check("www station allowed",
      seclogic.all_links_allowlisted("wallet at www.station.money"))
check("docs subdomain of cosmosrescue allowed",
      seclogic.all_links_allowlisted("https://docs.cosmosrescue.com/cosmobot/setup"))
check("t.me link NOT allowed",
      not seclogic.all_links_allowlisted("join t.me/freeluncdoubling"))
check("unknown domain NOT allowed",
      not seclogic.all_links_allowlisted("claim at https://free-lunc-claim.xyz"))
check("official + unknown mix NOT allowed",
      not seclogic.all_links_allowlisted("https://luncscan.com and https://evil-example.com"))
check("no links -> False (nothing to excuse)",
      not seclogic.all_links_allowlisted("just a normal first message"))
check("lookalike domain NOT allowed",
      not seclogic.all_links_allowlisted("https://luncscan.com.evil-example.com"))
check("hosts extracted",
      "finder.terraclassic.community" in seclogic.extract_hosts("x https://finder.terraclassic.community/a?b=1"))

# --- Fingerprints ---
LONG = "This is a very special giveaway message that scammers paste into many groups at once to steal funds."
LONG_OTHER_LINK = LONG + " https://scam-link-one.example/claim"
LONG_LINK2 = LONG + " https://different-link-two.example/win"
check("long message fingerprints", seclogic.fingerprint(LONG) is not None)
check("same text, different links -> same fingerprint",
      seclogic.fingerprint(LONG_OTHER_LINK) == seclogic.fingerprint(LONG_LINK2))
check("short message -> None", seclogic.fingerprint("gm everyone") is None)
check("different long text -> different fingerprint",
      seclogic.fingerprint(LONG) != seclogic.fingerprint("A completely different long announcement about validator upgrades and governance voting this week."))

# --- Fresh-looking accounts ---
check("no username + no photo = fresh", seclogic.fresh_looking(False, 0) is True)
check("username present = not fresh", seclogic.fresh_looking(True, 0) is False)
check("photo present = not fresh", seclogic.fresh_looking(False, 2) is False)
check("unknown photo count = not fresh (no guessing)", seclogic.fresh_looking(False, None) is False)

# --- Fresh holds (store) ---
check("no hold by default", store.fresh_get(-1001, 777) is None)
store.fresh_add(-1001, 777, 2000)
check("hold stored", store.fresh_get(-1001, 777)["until_ts"] == 2000)
check("not due before until", len(store.fresh_due(1999)) == 0)
check("due at until", len(store.fresh_due(2000)) == 1)
store.fresh_add(-1001, 777, 5000)
check("re-add extends", store.fresh_get(-1001, 777)["until_ts"] == 5000 and len(store.fresh_due(2000)) == 0)
check("hold remove works", store.fresh_remove(-1001, 777) == 1)
check("hold gone", store.fresh_get(-1001, 777) is None)

# --- Appeals (store) ---
check("no appeal by default", store.appeal_last(777) is None)
store.appeal_record(777, "global ban")
row = store.appeal_last(777)
check("appeal recorded", row is not None and row["kind"] == "global ban" and row["ts"] > 0)
store.appeal_record(777, "AI ban")
check("appeal upsert keeps 1 row", store.appeal_last(777)["kind"] == "AI ban")

print()
print("FAILURES:", fails if fails else "none")
sys.exit(1 if fails else 0)
