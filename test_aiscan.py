"""Tests for the AI scam scan (2026-11-21, aiscan.py + bot wiring).

Fail-safe contract under test:
- ordinary chat NEVER reaches the model (prefilter) and is never banned;
- only a strict, high-confidence SCAM verdict strikes (delete + ban);
- borderline / low-confidence / unparseable / AI-down = do nothing;
- group admins and the owner are NEVER scanned or banned, even when
  they post the exact scam script (e.g. quoting it to warn others);
- scan rate caps keep the daily AI pot safe.

The model is stubbed (ai_client.chat monkeypatched) — no network.
Run: python3 test_aiscan.py"""
import asyncio
import os
import sys
import tempfile
import types

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["OWNER_TELEGRAM_ID"] = "999"

# --- Dependency stubs (same pattern as test_autoban.py) ---
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
ext.ContextTypes = types.SimpleNamespace(DEFAULT_TYPE=object)
ext.filters = types.SimpleNamespace()
tg.ext = ext

sys.modules["telegram"] = tg
sys.modules["telegram.constants"] = constants
sys.modules["telegram.error"] = error
sys.modules["telegram.ext"] = ext

import ai_client
import aiscan
import bot
import store

OWNER, ADMIN, MEMBER, SPAMMER = 999, 444, 555, 31337
BOT_ID = 4242
GROUP = -100888

fails = []


def check(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        fails.append(name)


TARIFF_SCRIPT = ("I am from China. My company is engaged in international trade. "
                 "Many of our overseas partners need to use USDT for payments to "
                 "avoid tariffs. However, due to Chinese regulations we are "
                 "unable to buy large amounts. Contact me if you can supply USDT.")
NORMAL = ("Hey everyone, how is the market looking today? I think LUNC will "
          "recover this year, what do you all think about the burn?")
WARNING = ("Careful everyone: never share your seed phrase with anyone, and "
           "never verify your wallet on a random site — that is how people "
           "get drained. Admins will never DM you first.")
# The live miss (2026-11-21, General LUNC Chat, user "Judy"): a
# recruitment / cash-reward referral ad the scan never flagged.
JUDY = ("🔥 $1,000 CASH REWARD – GLOBAL RECRUITMENT! 💰 🌍 We are looking "
        "for experienced team leaders, market builders, and professionals "
        "in AI, Forex, cryptocurrency, and digital finance. 💎 Have a "
        "strong network? 🤝 Know experienced industry professionals? 🚀 "
        "Want to explore a new business partnership? Refer a qualified "
        "candidate who successfully joins the partnership and receive a "
        "$1,000 cash reward")
# Near-miss legit messages: recruitment-shaped words, no ad. None of
# these may ever strike.
LEGIT_VALIDATORS = ("We are looking for experienced validators to join our "
                    "network — if you run a solid node with good uptime, "
                    "the community would love more decentralization.")
LEGIT_REFERRAL_TALK = ("Did you see that post? Refer a friend to stake and "
                       "the protocol pays a bonus in LUNC. Sounds too easy — "
                       "is that legit or just marketing?")
LEGIT_JOB_ASK = ("Does anyone here know a legit project hiring blockchain "
                 "devs? I have been looking for work in crypto for weeks "
                 "and could use a pointer.")

# --- Prefilter units ---------------------------------------------------
check("prefilter: 'hello' too short + no signal", not aiscan.prefilter("hello"))
check("prefilter: ordinary chat does not pass", not aiscan.prefilter(NORMAL))
check("prefilter: tariff script passes", aiscan.prefilter(TARIFF_SCRIPT))
check("prefilter: scam-warning text passes (signal words) — model decides",
      aiscan.prefilter(WARNING))
check("prefilter: short spam stays out", not aiscan.prefilter("buy usdt @someone"))
check("prefilter: Judy's recruitment ad passes (reaches the model)",
      aiscan.prefilter(JUDY))
check("prefilter: validator-recruitment talk stays out",
      not aiscan.prefilter(LEGIT_VALIDATORS))
check("prefilter: job hunting stays out", not aiscan.prefilter(LEGIT_JOB_ASK))
check("classifier prompt names the recruitment/reward category",
      "referral-reward" in aiscan.SYSTEM and "global " in aiscan.SYSTEM)
check("classifier prompt protects discussion of such schemes",
      "only POSTING the" in aiscan.SYSTEM)

# --- Verdict parsing ----------------------------------------------------
check("parse: 'SCAM 92'", aiscan.parse_verdict("SCAM 92") == ("scam", 92))
check("parse: 'SCAM 85' at threshold", aiscan.parse_verdict("SCAM 85") == ("scam", 85))
check("parse: 'OK'", aiscan.parse_verdict("OK") == ("ok", None))
check("parse: rambling answer is not a verdict",
      aiscan.parse_verdict("This message looks like a scam because...") is None)
check("parse: 'SCAM' without a number is not a verdict",
      aiscan.parse_verdict("SCAM") is None)
check("parse: empty/None", aiscan.parse_verdict("") is None
      and aiscan.parse_verdict(None) is None)


async def fake_call(reply):
    async def _call(messages, temperature=0.3, lang="en"):
        return reply
    return _call


async def units():
    check("classify: SCAM 95 strikes",
          await aiscan.classify_scam(TARIFF_SCRIPT, call=await fake_call("SCAM 95")) == 95)
    check("classify: SCAM 84 (below threshold) does nothing",
          await aiscan.classify_scam(TARIFF_SCRIPT, call=await fake_call("SCAM 84")) is None)
    check("classify: OK does nothing",
          await aiscan.classify_scam(TARIFF_SCRIPT, call=await fake_call("OK")) is None)
    check("classify: AI down (None) does nothing",
          await aiscan.classify_scam(TARIFF_SCRIPT, call=await fake_call(None)) is None)
    check("classify: unparseable does nothing",
          await aiscan.classify_scam(TARIFF_SCRIPT, call=await fake_call("maybe")) is None)


asyncio.run(units())


# --- Wiring fakes (same shapes as test_autoban.py) ----------------------
def user(uid, username=None, is_bot=False):
    return types.SimpleNamespace(id=uid, full_name=f"U{uid}", username=username,
                                 is_bot=is_bot)


def chat(cid, title="Lunc Global Marketing Team"):
    return types.SimpleNamespace(id=cid, type="supergroup", title=title)


class FakeMsg:
    def __init__(self, ch, usr, text, mid=1):
        self.chat, self.from_user = ch, usr
        self.text = text
        self.message_id = mid
        self.entities = []
        self.caption_entities = []
        self.replies = []

    async def delete(self):
        pass

    async def reply_text(self, text, **kwargs):
        self.replies.append(text)


class FakeBot:
    def __init__(self):
        self.id = BOT_ID
        self.admins = set()
        self.bans = []
        self.deleted = []
        self.sent = []

    async def get_chat_member(self, chat_id, user_id):
        return types.SimpleNamespace(
            status="administrator" if (chat_id, user_id) in self.admins else "member")

    async def ban_chat_member(self, chat_id, user_id):
        self.bans.append((chat_id, user_id))

    async def unban_chat_member(self, chat_id, user_id, only_if_banned=False):
        pass

    async def delete_message(self, chat_id, message_id):
        self.deleted.append((chat_id, message_id))

    async def restrict_chat_member(self, *a, **k):
        pass

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append((chat_id, text, kwargs))

    async def get_me(self):
        return types.SimpleNamespace(username="LuncAssistantBot")


def upd(msg, usr):
    return types.SimpleNamespace(
        message=msg, effective_message=msg,
        effective_chat=msg.chat, effective_user=usr, edited_message=None)


def ctx(fb):
    return types.SimpleNamespace(bot=fb, args=[])


AI_CALLS = []
AI_REPLY = {"text": "OK"}


async def stub_chat(messages, temperature=0.3, lang="en"):
    AI_CALLS.append(messages)
    return AI_REPLY["text"]


ai_client.chat = stub_chat



def scan_calls():
    """AI calls made by the SCANNER (its system prompt), as opposed to
    other bot features (translate fallback etc.) that share ai_client."""
    return [m for m in AI_CALLS
            if m and m[0].get("role") == "system" and m[0].get("content") == aiscan.SYSTEM]


async def post(fb, usr, text, mid):
    bot.AISCAN_LIMITER.reset()
    m = FakeMsg(chat(GROUP), usr, text, mid=mid)
    await bot.on_message(upd(m, usr), ctx(fb))
    return m


async def main():
    spammer = user(SPAMMER, "hrchina")
    member = user(MEMBER, "regularjoe")
    admin = user(ADMIN, "groupadmin")
    owner = user(OWNER, "theowner")

    # Normal message: model never consulted, nothing happens.
    fb = FakeBot(); AI_CALLS.clear(); AI_REPLY["text"] = "SCAM 99"
    await post(fb, member, NORMAL, mid=10)
    check("e2e: normal message — model never called, no ban, no delete",
          scan_calls() == [] and fb.bans == [] and fb.deleted == [])

    # Tariff script + high-confidence SCAM: delete + ban.
    fb = FakeBot(); AI_CALLS.clear(); AI_REPLY["text"] = "SCAM 95"
    await post(fb, spammer, TARIFF_SCRIPT, mid=11)
    check("e2e: tariff script at SCAM 95 — banned",
          (GROUP, SPAMMER) in fb.bans)
    check("e2e: tariff script at SCAM 95 — message deleted",
          (GROUP, 11) in fb.deleted)

    # Same script, borderline verdict: nothing happens.
    fb = FakeBot(); AI_REPLY["text"] = "SCAM 60"
    await post(fb, spammer, TARIFF_SCRIPT, mid=12)
    check("e2e: tariff script at SCAM 60 (borderline) — no ban, no delete",
          fb.bans == [] and fb.deleted == [])

    # Same script, model says OK: nothing happens.
    fb = FakeBot(); AI_REPLY["text"] = "OK"
    await post(fb, spammer, TARIFF_SCRIPT, mid=13)
    check("e2e: script text but verdict OK — no ban, no delete",
          fb.bans == [] and fb.deleted == [])

    # Scam-warning post (prefilter passes) + verdict OK: nothing.
    fb = FakeBot(); AI_REPLY["text"] = "OK"
    await post(fb, member, WARNING, mid=14)
    check("e2e: member warning ABOUT scams — no ban, no delete",
          fb.bans == [] and fb.deleted == [])

    # Group admin posts the exact script (e.g. quoting it): the model
    # is never even consulted and the admin is never banned.
    fb = FakeBot(); fb.admins.add((GROUP, ADMIN))
    AI_CALLS.clear(); AI_REPLY["text"] = "SCAM 99"
    await post(fb, admin, TARIFF_SCRIPT, mid=15)
    check("e2e: group admin posting the script — never scanned, never banned",
          scan_calls() == [] and fb.bans == [] and fb.deleted == [])

    # Owner posts the exact script: never banned.
    fb = FakeBot(); AI_CALLS.clear(); AI_REPLY["text"] = "SCAM 99"
    await post(fb, owner, TARIFF_SCRIPT, mid=16)
    check("e2e: owner posting the script — never scanned, never banned",
          scan_calls() == [] and fb.bans == [] and fb.deleted == [])

    # AI down entirely: nothing happens.
    fb = FakeBot(); AI_REPLY["text"] = None
    await post(fb, spammer, TARIFF_SCRIPT, mid=17)
    check("e2e: AI down — no ban, no delete", fb.bans == [] and fb.deleted == [])

    # Judy's recruitment ad: high-confidence SCAM strikes.
    judy = user(777, "judy")
    fb = FakeBot(); AI_CALLS.clear(); AI_REPLY["text"] = "SCAM 95"
    await post(fb, judy, JUDY, mid=18)
    check("e2e: Judy recruitment ad at SCAM 95 — model was consulted",
          len(scan_calls()) == 1)
    check("e2e: Judy recruitment ad at SCAM 95 — banned",
          (GROUP, 777) in fb.bans)
    check("e2e: Judy recruitment ad at SCAM 95 — message deleted",
          (GROUP, 18) in fb.deleted)

    # Same ad, borderline verdict: nothing happens.
    fb = FakeBot(); AI_REPLY["text"] = "SCAM 60"
    await post(fb, judy, JUDY, mid=19)
    check("e2e: Judy ad at SCAM 60 (borderline) — no ban, no delete",
          fb.bans == [] and fb.deleted == [])

    # Near-miss legit messages never strike — even with a hostile
    # stub, the prefilter keeps them away from the model entirely.
    fb = FakeBot(); AI_CALLS.clear(); AI_REPLY["text"] = "SCAM 99"
    await post(fb, member, LEGIT_VALIDATORS, mid=20)
    await post(fb, member, LEGIT_JOB_ASK, mid=21)
    check("e2e: validator-recruitment + job-ask — model never called, no ban",
          scan_calls() == [] and fb.bans == [] and fb.deleted == [])

    # Referral-program DISCUSSION with a sane verdict: nothing.
    fb = FakeBot(); AI_REPLY["text"] = "OK"
    await post(fb, member, LEGIT_REFERRAL_TALK, mid=22)
    check("e2e: referral-bonus discussion, verdict OK — no ban, no delete",
          fb.bans == [] and fb.deleted == [])

    # Rate cap: the same user can only be scanned 3x/hour.
    fb = FakeBot(); AI_REPLY["text"] = "SCAM 95"
    bot.AISCAN_LIMITER.reset()
    reasons = []
    for i in range(4):
        reasons.append(await bot._aiscan_maybe(ctx(fb), chat(GROUP), spammer, TARIFF_SCRIPT))
    check("limiter: first 3 scans allowed, 4th capped",
          reasons[:3] == ["aiscam"] * 3 and reasons[3] is None)


asyncio.run(main())
print()
if fails:
    print(f"{len(fails)} FAILURES:", fails)
    sys.exit(1)
print("ALL PASS")
