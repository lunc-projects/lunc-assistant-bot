"""Wallet Security tests (2026-10-29): strict bech32 validation,
per-user/global caps, silent baselines, per-category diffs,
skip-on-partial-read, duplicate suppression, DM-only routing, and
SQL-injection payloads on every new input.

Run: python3 test_walletwatch.py"""
import asyncio
import hashlib
import json
import os
import sys
import tempfile
import types

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
_TMP = tempfile.mkdtemp()
os.environ["DB_PATH"] = os.path.join(_TMP, "test.db")
os.environ["OWNER_TELEGRAM_ID"] = "999"

sys.modules.setdefault("httpx", types.ModuleType("httpx"))

tg = types.ModuleType("telegram")


class _Button:
    def __init__(self, text, callback_data=None, url=None, web_app=None, **_):
        self.text = text
        self.callback_data = callback_data
        self.url = url
        self.web_app = web_app


class _Markup:
    def __init__(self, inline_keyboard):
        self.inline_keyboard = inline_keyboard


class _Perms:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class _WebApp:
    def __init__(self, url):
        self.url = url


class _GameResult:
    def __init__(self, id, game_short_name):
        self.id = id
        self.game_short_name = game_short_name


tg.Update = object
tg.InlineKeyboardButton = _Button
tg.InlineKeyboardMarkup = _Markup
tg.ChatPermissions = _Perms
tg.WebAppInfo = _WebApp
tg.InlineQueryResultGame = _GameResult

constants = types.ModuleType("telegram.constants")
constants.ParseMode = types.SimpleNamespace(MARKDOWN="Markdown", HTML="HTML")
tg.constants = constants

error = types.ModuleType("telegram.error")


class _BadRequest(Exception):
    pass


error.BadRequest = _BadRequest
tg.error = error

ext = types.ModuleType("telegram.ext")


class _DummyHandler:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs


ext.Application = _DummyHandler
ext.CommandHandler = _DummyHandler
ext.MessageHandler = _DummyHandler
ext.CallbackQueryHandler = _DummyHandler
ext.InlineQueryHandler = _DummyHandler
ext.TypeHandler = _DummyHandler
ext.ContextTypes = types.SimpleNamespace(DEFAULT_TYPE=object)
ext.filters = types.SimpleNamespace()
tg.ext = ext

sys.modules["telegram"] = tg
sys.modules["telegram.constants"] = constants
sys.modules["telegram.error"] = error
sys.modules["telegram.ext"] = ext

import store
import walletwatch

fails = []


def check(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        fails.append(name)


NS = types.SimpleNamespace

# --- bech32 ENCODER (test-side, independent of the module's decoder)
_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def _polymod(values):
    chk = 1
    gen = (0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)
    for v in values:
        top = chk >> 25
        chk = ((chk & 0x1FFFFFF) << 5) ^ v
        for i in range(5):
            if (top >> i) & 1:
                chk ^= gen[i]
    return chk


def _convertbits(data, frm, to, pad=True):
    acc, bits, ret = 0, 0, []
    maxv = (1 << to) - 1
    for b in data:
        acc = (acc << frm) | b
        bits += frm
        while bits >= to:
            bits -= to
            ret.append((acc >> bits) & maxv)
    if pad and bits:
        ret.append((acc << (to - bits)) & maxv)
    return ret


def bech32_encode(payload_bytes):
    hrp = "terra"
    data = _convertbits(payload_bytes, 8, 5)
    vals = [ord(x) >> 5 for x in hrp] + [0] + [ord(x) & 31 for x in hrp] + data + [0] * 6
    pm = _polymod(vals) ^ 1
    checksum = [(pm >> 5 * (5 - i)) & 31 for i in range(6)]
    return hrp + "1" + "".join(_CHARSET[d] for d in data + checksum)


ADDR1 = bech32_encode(bytes(range(20)))
ADDR2 = bech32_encode(bytes(range(20, 40)))
ADDR3 = bech32_encode(b"\xaa" * 20)
ADDR4 = bech32_encode(b"\xbb" * 20)
CONTRACT1 = bech32_encode(bytes(range(32)))
VALOPER = "terravaloper1" + "q" * 29  # label only; diff treats it as a key

# ============ Validation ============
check("encoder address is 44 chars", len(ADDR1) == 44)
check("valid account address passes", walletwatch.validate_account_address(ADDR1))
check("valid second address passes", walletwatch.validate_account_address(ADDR2))
check("contract (64) passes contract validation", walletwatch.validate_contract_address(CONTRACT1))
check("contract fails ACCOUNT validation (length class)", not walletwatch.validate_account_address(CONTRACT1))
check("account fails CONTRACT validation", not walletwatch.validate_contract_address(ADDR1))
_bad = ADDR1[:20] + ("q" if ADDR1[20] != "q" else "p") + ADDR1[21:]
check("one flipped char fails checksum", not walletwatch.validate_account_address(_bad))
check("uppercase rejected", not walletwatch.validate_account_address(ADDR1.upper()))
check("too short rejected", not walletwatch.validate_account_address(ADDR1[:-1]))
check("too long rejected", not walletwatch.validate_account_address(ADDR1 + "q"))
check("wrong prefix rejected", not walletwatch.validate_account_address("cosmos" + ADDR1[5:]))
check("empty rejected", not walletwatch.validate_account_address(""))
check("non-string rejected", not walletwatch.validate_account_address(None))

PAYLOADS = [
    "terra1'; DROP TABLE wallet_watches;--",
    'terra1" OR "1"="1',
    "terra1" + "q" * 500,
    "terra1\\'; DELETE FROM messages; --",
    "terra1%27%20OR%201=1",
    "'; INSERT INTO wallet_watches VALUES(1,'x',1,'',0); --",
    "terra1qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq",  # right shape class, bad checksum
]
for i, p in enumerate(PAYLOADS):
    check(f"injection payload {i} rejected by account validation",
          not walletwatch.validate_account_address(p))
    check(f"injection payload {i} rejected by contract validation",
          not walletwatch.validate_contract_address(p))

# ============ Store: registration, caps, privacy of rows ============
S0 = json.dumps({"balances": {"uluna": "1000000"}})
check("add wallet 1", store.wallet_watch_add(111, ADDR1, S0) == "added")
check("add wallet 2", store.wallet_watch_add(111, ADDR2, S0) == "added")
check("add wallet 3", store.wallet_watch_add(111, ADDR3, S0) == "added")
check("4th wallet hits the per-user cap", store.wallet_watch_add(111, ADDR4, S0) == "user_cap")
check("re-adding an existing wallet refreshes, not duplicates",
      store.wallet_watch_add(111, ADDR1, S0) == "exists"
      and len(store.wallet_watch_list(111)) == 3)
check("another user has their own separate list",
      store.wallet_watch_add(222, ADDR1, S0) == "added"
      and len(store.wallet_watch_list(222)) == 1)
check("user 111 cannot remove user 222's watch (keyed rows)",
      store.wallet_watch_remove(222, ADDR2) == 0
      and len(store.wallet_watch_list(111)) == 3)
check("remove own wallet works", store.wallet_watch_remove(111, ADDR3) == 1)

store.WALLET_WATCH_GLOBAL_CAP = 4  # 111:2 + 222:1 = 3 rows now; cap at 4
check("one more fits under global cap", store.wallet_watch_add(333, ADDR2, S0) == "added")
check("next hits the global cap with an honest state",
      store.wallet_watch_add(333, ADDR3, S0) == "global_cap")
store.WALLET_WATCH_GLOBAL_CAP = 500

# Store-level payloads: parameterized SQL treats them as data.
n_before = store.wallet_watch_counts()["watches"]
store.wallet_watch_add(999, PAYLOADS[0], S0)  # cannot validate, but even direct: inert
rows = store.wallet_watch_list(999)
check("payload stored as inert data, tables intact",
      store.wallet_watch_counts()["watches"] == n_before + 1 and rows and rows[0]["address"] == PAYLOADS[0])
store.wallet_watch_remove(999, PAYLOADS[0])
check("payload row removable, counts back", store.wallet_watch_counts()["watches"] == n_before)
import sqlite3
c = sqlite3.connect(store.DB)
tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
c.close()
check("wallet_watches + messages tables still exist after payloads",
      "wallet_watches" in tables and "messages" in tables)

# Pause / resume
store.wallet_watch_set_active(111, False)
check("pause switches all of the user's watches off",
      all(r["active"] == 0 for r in store.wallet_watch_list(111)))
check("paused watches are not due", all(r["user_id"] != 111 for r in store.wallet_watch_due(50)))
store.wallet_watch_set_active(111, True)
check("resume switches them back on", all(r["active"] == 1 for r in store.wallet_watch_list(111)))

# Contracts
check("attach contract", store.watch_contract_add(111, CONTRACT1, "cw20") == "added")
check("attach same contract again -> exists", store.watch_contract_add(111, CONTRACT1, "cw20") == "exists")
check("contracts are per-user", store.watch_contracts_for(222) == [])
check("detach contract", store.watch_contract_remove(111, CONTRACT1) == 1)

# Dedupe log
h = walletwatch.change_key({"kind": "balance", "key": "uluna", "old": "1", "new": "2"})
check("unseen change is not 'seen'", not store.watch_alert_seen(111, ADDR1, h, 1000, 86400))
store.watch_alert_mark(111, ADDR1, h, 1000)
check("marked change is seen inside the window", store.watch_alert_seen(111, ADDR1, h, 1000 + 3600, 86400))
check("same change is NOT seen after the window", not store.watch_alert_seen(111, ADDR1, h, 1000 + 90000, 86400))
check("dedupe is per-user", not store.watch_alert_seen(222, ADDR1, h, 1000 + 10, 86400))

# ============ Diffing ============
BASE = {
    "balances": {"uluna": "100000000", "uusd": "5000000"},
    "delegations": {VALOPER: "50000000"},
    "unbonding": {},
    "cw20": {CONTRACT1: {"balance": "700", "symbol": "FRGX", "decimals": 6}},
    "nfts": {CONTRACT1: {"name": "Test NFTs", "tokens": ["1", "2"]}},
}
check("baseline (empty old) never alerts", walletwatch.diff_states({}, BASE) == [])
check("identical states -> no changes", walletwatch.diff_states(BASE, json.loads(json.dumps(BASE))) == [])

import copy
s2 = copy.deepcopy(BASE); s2["balances"]["uluna"] = "90000000"
d = walletwatch.diff_states(BASE, s2)
check("balance decrease detected", len(d) == 1 and d[0]["kind"] == "balance" and d[0]["key"] == "uluna")

s3 = copy.deepcopy(BASE); s3["delegations"][VALOPER] = "60000000"
d = walletwatch.diff_states(BASE, s3)
check("delegation increase detected", len(d) == 1 and d[0]["kind"] == "delegation")

s4 = copy.deepcopy(BASE); del s4["delegations"][VALOPER]
d = walletwatch.diff_states(BASE, s4)
check("full undelegation detected", len(d) == 1 and d[0]["kind"] == "delegation" and d[0]["new"] == "0")

s5 = copy.deepcopy(BASE); s5["unbonding"][VALOPER] = {"total": "5000000", "entries": 1}
d = walletwatch.diff_states(BASE, s5)
check("unbonding start detected", len(d) == 1 and d[0]["kind"] == "unbonding")

s6 = copy.deepcopy(BASE); s6["cw20"][CONTRACT1]["balance"] = "701"
d = walletwatch.diff_states(BASE, s6)
check("cw20 change detected with symbol", len(d) == 1 and d[0]["kind"] == "cw20" and d[0]["symbol"] == "FRGX")

s7 = copy.deepcopy(BASE); s7["nfts"][CONTRACT1]["tokens"] = ["2", "3"]
d = walletwatch.diff_states(BASE, s7)
kinds = sorted(c["kind"] for c in d)
check("NFT in + out both detected", kinds == ["nft_in", "nft_out"])

# Formatting
txt = walletwatch.format_alert(ADDR1, walletwatch.diff_states(BASE, s2) + walletwatch.diff_states(BASE, s7))
check("alert names the wallet + finder account link",
      ADDR1 in txt and f"/account/{ADDR1}" in txt)
check("alert shows the LUNC delta", "-10 LUNC" in txt)
check("alert carries the security guidance", "treat it as a security issue" in txt)
check("amount formatter groups + trims", walletwatch.fmt_amount("1234567890000", 6) == "1,234,567.89")

# ============ Job behaviour (fakes) ============
import bot

sent = []


class _JobBot:
    async def send_message(self, chat_id, text, parse_mode=None):
        sent.append((chat_id, text))


# clean slate: remove EVERY user's watches so the job section
# below sees exactly one watch (777's) in the whole test DB.
for _u in (111, 222, 333, 777, 888, 999):
    for r in store.wallet_watch_list(_u):
        store.wallet_watch_remove(_u, r["address"])
store.wallet_watch_add(777, ADDR2, "")  # empty snapshot = baselines silently

STATE_A = {"balances": {"uluna": "1000000"}, "delegations": {}, "unbonding": {}, "cw20": {}, "nfts": {}}
STATE_B = {"balances": {"uluna": "2000000"}, "delegations": {}, "unbonding": {}, "cw20": {}, "nfts": {}}
_script = {"state": STATE_A, "fail": False}


async def _fake_fetch(address, contracts):
    # Only 777's wallet (ADDR2) follows the script; every other
    # watch in the shared test DB gets a state identical to its
    # stored snapshot, so it can never produce a change.
    if address != ADDR2:
        return {"balances": {"uluna": "1000000"}, "delegations": {},
                "unbonding": {}, "cw20": {}, "nfts": {}}
    if _script["fail"]:
        raise RuntimeError("LCD down")
    return _script["state"]


_real_fetch = bot.fetch_wallet_state
bot.fetch_wallet_state = _fake_fetch
try:
    asyncio.run(bot.job_wallet_watch(NS(bot=_JobBot())))
    check("first sighting baselines silently (no DM)", sent == [])
    snap = json.loads(store.wallet_watch_list(777)[0]["snapshot"])
    check("baseline snapshot stored", snap == STATE_A)

    _script["state"] = STATE_B
    asyncio.run(bot.job_wallet_watch(NS(bot=_JobBot())))
    check("change DMs the registrant ONLY", len(sent) == 1 and sent[0][0] == 777)
    check("DM describes the change", "1,000,000" not in sent[0][1] and "+1 LUNC" in sent[0][1])
    snap = json.loads(store.wallet_watch_list(777)[0]["snapshot"])
    check("snapshot advanced after alert", snap == STATE_B)

    asyncio.run(bot.job_wallet_watch(NS(bot=_JobBot())))
    check("no repeat DM when nothing changed", len(sent) == 1)

    _script["fail"] = True
    asyncio.run(bot.job_wallet_watch(NS(bot=_JobBot())))
    check("failed chain read: silent skip, no DM", len(sent) == 1)
    snap = json.loads(store.wallet_watch_list(777)[0]["snapshot"])
    check("failed chain read: snapshot untouched", snap == STATE_B)
    _script["fail"] = False
finally:
    bot.fetch_wallet_state = _real_fetch

# ============ Handlers: group gate + validation + DM flow ============
replies = []


class _HMsg:
    def __init__(self):
        self.texts = []

    async def reply_text(self, text, parse_mode=None, **kw):
        self.texts.append(text)
        replies.append(text)


def _upd(chat_type, uid, args):
    return NS(effective_chat=NS(id=uid if chat_type == "private" else -555, type=chat_type),
              effective_user=NS(id=uid), effective_message=_HMsg())


bot.fetch_wallet_state = _fake_fetch
try:
    asyncio.run(bot.on_watch(_upd("group", 888, [ADDR1]), NS(args=[ADDR1])))
    check("group /watch redirects to DM", replies and "DM me" in replies[-1])
    check("group /watch registered NOTHING", store.wallet_watch_list(888) == [])

    replies.clear()
    asyncio.run(bot.on_watch(_upd("private", 888, [PAYLOADS[0]]), NS(args=[PAYLOADS[0]])))
    check("DM /watch with injection payload -> invalid, nothing stored",
          replies and "doesn't validate" in replies[-1] and store.wallet_watch_list(888) == [])

    replies.clear()
    asyncio.run(bot.on_watch(_upd("private", 888, [ADDR1]), NS(args=[ADDR1])))
    check("DM /watch registers + confirms", replies and "Watching" in replies[-1]
          and len(store.wallet_watch_list(888)) == 1)

    replies.clear()
    asyncio.run(bot.on_watching(_upd("group", 888, []), NS(args=[])))
    check("group /watching reveals nothing, points to DM",
          replies and "private" in replies[-1] and ADDR1 not in replies[-1])

    replies.clear()
    asyncio.run(bot.on_watch(_upd("private", 888, ["off"]), NS(args=["off"])))
    check("/watch off pauses", replies and "paused" in replies[-1]
          and store.wallet_watch_list(888)[0]["active"] == 0)

    replies.clear()
    asyncio.run(bot.on_unwatch(_upd("private", 888, [ADDR1]), NS(args=[ADDR1])))
    check("/unwatch removes", replies and "Stopped watching" in replies[-1]
          and store.wallet_watch_list(888) == [])
finally:
    bot.fetch_wallet_state = _real_fetch

# ============ Sweep health: never fail silently ============
health = []


class _HealthBot:
    async def send_message(self, chat_id, text, parse_mode=None):
        health.append((chat_id, text))


# clean slate again: exactly one watch (777 / ADDR2), baseline STATE_A
for _u in (111, 222, 333, 777, 888, 999):
    for r in store.wallet_watch_list(_u):
        store.wallet_watch_remove(_u, r["address"])
store.wallet_watch_add(777, ADDR2, json.dumps(STATE_A))
store.set_setting(0, "ww_fail_streak", "0")
store.set_setting(0, "ww_last_success", "0")
store.set_setting(0, "ww_health_alert_ts", "0")
store.set_setting(0, "ww_alerted", "0")

bot.fetch_wallet_state = _fake_fetch
try:
    _script["state"] = STATE_A
    _script["fail"] = True
    asyncio.run(bot.job_wallet_watch(NS(bot=_HealthBot())))
    asyncio.run(bot.job_wallet_watch(NS(bot=_HealthBot())))
    check("2 failed sweeps: streak=2, owner NOT yet alerted",
          store.get_setting(0, "ww_fail_streak") == "2"
          and [m for m in health if m[0] == 999] == [])
    asyncio.run(bot.job_wallet_watch(NS(bot=_HealthBot())))
    owner_msgs = [m for m in health if m[0] == 999]
    check("3rd consecutive failed sweep: owner alerted exactly once",
          len(owner_msgs) == 1 and "consecutive wallet sweeps have failed" in owner_msgs[0][1])
    check("users got NO health noise (no DM to 777)",
          [m for m in health if m[0] == 777] == [])
    asyncio.run(bot.job_wallet_watch(NS(bot=_HealthBot())))
    check("4th failed sweep: throttled, still one owner alert",
          len([m for m in health if m[0] == 999]) == 1)
    store.set_setting(0, "ww_health_alert_ts", "0")  # simulate 6h passing
    asyncio.run(bot.job_wallet_watch(NS(bot=_HealthBot())))
    check("still failing after the throttle gap: owner re-alerted",
          len([m for m in health if m[0] == 999]) == 2)

    _script["fail"] = False
    asyncio.run(bot.job_wallet_watch(NS(bot=_HealthBot())))
    check("recovery: streak reset + last-success recorded",
          store.get_setting(0, "ww_fail_streak") == "0"
          and int(store.get_setting(0, "ww_last_success") or 0) > 0)
    check("recovery: owner gets the all-clear",
          any("recovered" in m[1] for m in health if m[0] == 999))
finally:
    bot.fetch_wallet_state = _real_fetch

# Watchdog: watches exist but no sweep ATTEMPT for >2x interval.
health.clear()
_real_started = bot._WW_STARTED
try:
    bot._WW_STARTED = 1  # process "started long ago"
    store.set_setting(0, "ww_last_attempt", "1")
    store.set_setting(0, "ww_health_alert_ts", "0")
    asyncio.run(bot.job_wallet_watchdog(NS(bot=_HealthBot())))
    check("watchdog fires when sweeps stopped running",
          len(health) == 1 and health[0][0] == 999 and "watchdog" in health[0][1])
    health.clear()
    import time as _t
    store.set_setting(0, "ww_last_attempt", str(int(_t.time())))
    asyncio.run(bot.job_wallet_watchdog(NS(bot=_HealthBot())))
    check("watchdog quiet when sweeps are running", health == [])
finally:
    bot._WW_STARTED = _real_started

# /botstats exposure: last successful sweep is in the counts + text.
rc = bot._report_counts()
check("report counts carry ww_last_success", rc.get("ww_last_success", 0) > 0)
_txt = bot.format_usage_report(rc, {"groups": 1, "people_in_groups": 2, "dm_users": 1, "messages": 3}, 0, 200000)
check("report text shows last successful sweep", "last successful sweep:" in _txt)

# ============ Downtime honesty: down notice, resume, gap diff ============
dt = []


class _DtBot:
    async def send_message(self, chat_id, text, parse_mode=None):
        dt.append((chat_id, text))


# slate: 777 (ADDR2, baseline STATE_A) + 888 (ADDR1) active;
# 555 has only a PAUSED watch and must hear nothing.
for _u in (111, 222, 333, 555, 777, 888, 999):
    for r in store.wallet_watch_list(_u):
        store.wallet_watch_remove(_u, r["address"])
_STATIC = {"balances": {"uluna": "1000000"}, "delegations": {}, "unbonding": {}, "cw20": {}, "nfts": {}}
store.wallet_watch_add(777, ADDR2, json.dumps(STATE_A))
store.wallet_watch_add(888, ADDR1, json.dumps(_STATIC))
store.wallet_watch_add(555, ADDR3, json.dumps(_STATIC))
store.wallet_watch_set_active(555, False)

asyncio.run(bot.post_shutdown(NS(bot=_DtBot())))
down_777 = [m for m in dt if m[0] == 777]
down_888 = [m for m in dt if m[0] == 888]
check("shutdown: each active watcher got exactly one down-notice",
      len(down_777) == 1 and len(down_888) == 1)
check("shutdown: down-notice is the owner's exact wording",
      down_777 and down_777[0][1] == bot.WW_DOWN_TEXT
      and "temporarily unprotected" in down_777[0][1]
      and "security update is in progress" in down_777[0][1])
check("shutdown: paused-only user got nothing",
      [m for m in dt if m[0] == 555] == [])
check("shutdown: down flag recorded", store.get_setting(0, "ww_down_announced") == "1")

# Resume: previous attempt 2h ago; 777's wallet changed meanwhile.
dt.clear()
import time as _time
bot._WW_PREV_ATTEMPT = int(_time.time()) - 7200
bot._WW_BACK_SENT = False
_script["state"] = {"balances": {"uluna": "3000000"}, "delegations": {}, "unbonding": {}, "cw20": {}, "nfts": {}}
_script["fail"] = False
bot.fetch_wallet_state = _fake_fetch
try:
    asyncio.run(bot.job_wallet_watch(NS(bot=_DtBot())))
finally:
    bot.fetch_wallet_state = _real_fetch
to777 = [m[1] for m in dt if m[0] == 777]
to888 = [m[1] for m in dt if m[0] == 888]
check("resume: watcher told protection is back (owner wording)",
      any("security update complete" in t and "protected again" in t for t in to777))
check("resume: offline window stated (~2h)",
      any("offline for about 2h" in t for t in to777))
check("resume: second watcher also got the back-notice",
      any("security update complete" in t for t in to888))
check("gap diff: downtime change alerted, labeled found-on-return",
      any("found on return" in t and "+2 LUNC" in t for t in to777))
check("gap diff: unchanged wallet got NO change alert",
      not any("change detected" in t for t in to888))

# Fresh-install boot (no previous attempt): no back-notice at all.
dt.clear()
bot._WW_PREV_ATTEMPT = 0
bot._WW_BACK_SENT = False
bot.fetch_wallet_state = _fake_fetch
try:
    asyncio.run(bot.job_wallet_watch(NS(bot=_DtBot())))
finally:
    bot.fetch_wallet_state = _real_fetch
check("fresh boot: no protection-back noise",
      not any("security update complete" in m[1] for m in dt))
bot._WW_PREV_ATTEMPT = 0
bot._WW_BACK_SENT = False

check("intro names the feature Wallet Security",
      "Wallet Security" in bot.WALLET_SECURITY_INTRO)
check("intro is honest about detection-only", "cannot prevent or reverse" in bot.WALLET_SECURITY_INTRO)
check("intro states read-only / no keys", "never ask for a seed phrase" in bot.WALLET_SECURITY_INTRO)

# ============ Finder links: full address, never a placeholder ====
# Regression pin (2026-10-30, owner's live test): the /watch success
# reply built its "Full view" URL in a plain (non-f-string) segment,
# so the user got ".../account/{a}" — a dead link. Every
# wallet-security message must carry the FULL address in its finder
# URL and no unexpanded "{...}" placeholder anywhere.
FINDER = "https://finder.terraclassic.community/mainnet"

bot.fetch_wallet_state = _fake_fetch
try:
    replies.clear()
    asyncio.run(bot.on_watch(_upd("private", 4242, [ADDR1]), NS(args=[ADDR1])))
    r = replies[-1]
    check("link pin: fresh /watch reply has the FULL address finder URL",
          f"{FINDER}/account/{ADDR1}" in r)
    check("link pin: fresh /watch reply has no unexpanded placeholder",
          "{" not in r and "}" not in r)

    replies.clear()
    asyncio.run(bot.on_watch(_upd("private", 4242, [ADDR1]), NS(args=[ADDR1])))
    r = replies[-1]
    check("link pin: re-watch (exists) reply has the FULL address finder URL",
          f"{FINDER}/account/{ADDR1}" in r)
    check("link pin: re-watch reply has no unexpanded placeholder",
          "{" not in r and "}" not in r)

    replies.clear()
    asyncio.run(bot.on_watching(_upd("private", 4242, []), NS(args=[])))
    r = replies[-1]
    check("link pin: /watching lists the FULL address finder URL",
          f"{FINDER}/account/{ADDR1}" in r)
    check("link pin: /watching has no unexpanded placeholder",
          "{" not in r and "}" not in r)

    # Attach-contract branch (kind lookup stubbed: no network here).
    async def _fake_kind(addr):
        return "cw20"
    _real_kind = bot.chain.contract_kind
    bot.chain.contract_kind = _fake_kind
    try:
        replies.clear()
        asyncio.run(bot.on_watch(_upd("private", 4242, [CONTRACT1]), NS(args=[CONTRACT1])))
        r = replies[-1]
    finally:
        bot.chain.contract_kind = _real_kind
    check("link pin: attach reply has the FULL contract finder URL",
          f"{FINDER}/account/{CONTRACT1}" in r)
    check("link pin: attach reply has no unexpanded placeholder",
          "{" not in r and "}" not in r)
finally:
    bot.fetch_wallet_state = _real_fetch

# Alert DMs across every change kind (normal + found-on-return).
_all = (walletwatch.diff_states(BASE, s2) + walletwatch.diff_states(BASE, s3)
        + walletwatch.diff_states(BASE, s6) + walletwatch.diff_states(BASE, s7))
atxt = walletwatch.format_alert(ADDR1, _all) + walletwatch.format_alert(ADDR1, _all, away=True)
check("link pin: alert DM has full wallet + token + validator finder URLs",
      f"/account/{ADDR1}" in atxt and f"/account/{CONTRACT1}" in atxt
      and f"/validator/{VALOPER}" in atxt)
check("link pin: alert DM has no unexpanded placeholder",
      "{" not in atxt and "}" not in atxt)
check("link pin: /security intro has no unexpanded placeholder",
      "{" not in bot.WALLET_SECURITY_INTRO and "}" not in bot.WALLET_SECURITY_INTRO)

# Static pin for the whole habit: no plain (non-f-string) string
# literal in bot.py / walletwatch.py may carry a "{name}" token —
# that is exactly how the dead {a} link shipped. (lang.py templates
# are exempt by design: lang.t() .format()s them at the call site,
# and both call sites pass name=.)
import ast as _ast
import re as _re

_TOKEN_RE = _re.compile(r"\{[A-Za-z_][A-Za-z0-9_.\[\]'\"]*\}")


def _plain_placeholder_hits(fname):
    tree = _ast.parse(open(os.path.join(ROOT, fname), encoding="utf-8").read())
    joined = set()
    for node in _ast.walk(tree):
        if isinstance(node, _ast.JoinedStr):
            for v in node.values:
                joined.add(id(v))
    return [node.lineno for node in _ast.walk(tree)
            if isinstance(node, _ast.Constant) and isinstance(node.value, str)
            and id(node) not in joined and _TOKEN_RE.search(node.value)]


check("link pin: bot.py has no plain-string placeholders",
      _plain_placeholder_hits("bot.py") == [])
check("link pin: walletwatch.py has no plain-string placeholders",
      _plain_placeholder_hits("walletwatch.py") == [])

print()
if fails:
    print("FAILURES:", len(fails))
    sys.exit(1)
print("ALL PASS")
