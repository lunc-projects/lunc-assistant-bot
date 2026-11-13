"""Tests for auto-ban (2026-11-13): the incident attack patterns.

Pure classifiers (autoban.py): bare bot-link list, payment-scam bait
+ contact, the link-only repeat tracker, report-button URL, evidence
text. Wiring (bot.py on_message + _send_ai_text linkage): delete +
permanent ban + propagation + owner evidence DM with the 🚩 button,
and the owner/admin/elevated/self exemptions.

Run: python3 test_autoban.py"""
import asyncio
import os
import sys
import tempfile
import types

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["OWNER_TELEGRAM_ID"] = "999"

# --- Dependency stubs (same pattern as test_del.py / test_filter.py) ---
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

import autoban
import bot
import store

OWNER, ADMIN, ELEV, SPAM, SPAM2, MEMBER = 999, 777, 888, 555, 556, 557
BOT_ID = 4242
GA, GB, GC = -100111, -100222, -100333
INCIDENT_LINKS = "@gAm0kiGk8bot\n@gbrcm9dfdbot\n@GIU3YH3Lbot"
INCIDENT_AD = (
    "We are unable to buy USDT in bulk through standard channels, so we "
    "want to acquire it at prices 5%-20% above the market rate. "
    "(We offer the best rates and the most secure transaction methods "
    "available.) Once we confirm you hold the USDT, we will make the "
    "payment first, and then you transfer the USDT to us. If you are a "
    "seller looking to sell USDT, please contact me Telegram: "
    "@YLzhangwei888")

fails = []
_total = [0]


def check(name, cond):
    _total[0] += 1
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        fails.append(name)


# --- Pure classifiers -------------------------------------------------
check("incident bot list (newlines) -> botlist",
      autoban.classify(INCIDENT_LINKS) == "botlist")
check("incident bot list (one line) -> botlist",
      autoban.classify("@gAm0kiGk8bot @gbrcm9dfdbot @GIU3YH3Lbot") == "botlist")
check("t.me bot links x2 -> botlist",
      autoban.classify("t.me/gAm0kiGk8bot t.me/GIU3YH3Lbot") == "botlist")
check("single bot mention alone -> no trigger",
      autoban.classify("@gAm0kiGk8bot") is None)
check("bot mentions inside a sentence -> no trigger",
      autoban.classify("ask @gAm0kiGk8bot or @gbrcm9dfdbot for help please") is None)
check("incident ad -> scam", autoban.classify(INCIDENT_AD) == "scam")
check("scam phrase without contact -> no trigger",
      autoban.classify("our pool pays above the market rate this week") is None)
check("contact without scam phrase -> no trigger",
      autoban.classify("thanks @YLzhangwei888 that was fast") is None)
check("normal sentence with a link -> no trigger",
      autoban.classify("look at this chart https://example.com/chart it is wild") is None)
check("plain chat -> no trigger", autoban.classify("good morning everyone") is None)
check("link-only detector: bare url", autoban.is_link_only("https://example.com/x"))
check("link-only detector: sentence is not link-only",
      not autoban.is_link_only("see https://example.com/x now"))

_tr = autoban.LinkOnlyTracker(window=600, threshold=2)
check("tracker: first link-only post does not fire", _tr.note(GA, SPAM, 10, ts=1000) is None)
check("tracker: second inside window fires with both ids",
      _tr.note(GA, SPAM, 11, ts=1200) == [10, 11])
check("tracker: resets after firing", _tr.note(GA, SPAM, 12, ts=1300) is None)
_tr2 = autoban.LinkOnlyTracker(window=600, threshold=2)
_tr2.note(GA, SPAM, 20, ts=1000)
check("tracker: hit after window does not fire", _tr2.note(GA, SPAM, 21, ts=1700) is None)
check("tracker: other user unaffected", _tr2.note(GA, MEMBER, 22, ts=1701) is None)

check("report url with username", autoban.report_url("spamuser", 555) == "https://t.me/spamuser")
check("report url without username", autoban.report_url(None, 555) == "tg://user?id=555")
_ev = autoban.evidence_text("Spam User", "spamuser", 555, "Terra Luna Classic Chat",
                            GA, "2026-11-13 08:03", "botlist", "x" * 200)
check("evidence has who/where/when", "spamuser" in _ev and "555" in _ev
      and "Terra Luna Classic Chat" in _ev and "2026-11-13 08:03" in _ev)
check("evidence truncates post to 120 chars", ("x" * 120) in _ev and ("x" * 121) not in _ev)


# --- Wiring fakes ------------------------------------------------------
def user(uid, username=None, is_bot=False):
    return types.SimpleNamespace(id=uid, full_name=f"U{uid}", username=username,
                                 is_bot=is_bot)


def chat(cid, title="Terra Luna Classic Chat"):
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
        self.sent = []          # (chat_id, text, kwargs)
        self.fail_bans = set()  # chat ids where ban raises (bot not admin)

    async def get_chat_member(self, chat_id, user_id):
        return types.SimpleNamespace(
            status="administrator" if (chat_id, user_id) in self.admins else "member")

    async def ban_chat_member(self, chat_id, user_id):
        if chat_id in self.fail_bans:
            raise RuntimeError("not an admin here")
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


def owner_dms(fb):
    return [s for s in fb.sent if s[0] == OWNER]


async def post(fb, usr, cid, text, mid):
    m = FakeMsg(chat(cid), usr, text, mid=mid)
    await bot.on_message(upd(m, usr), ctx(fb))
    return m


# Propagation targets: GB via the mod list, GC via the usage registry.
store.mod_request_group(GB, "Group B", OWNER)
store.mod_approve_group(GB)
store.observe_update(chat_id=GC, chat_type="supergroup", user_id=None,
                     kind="message", is_member=True, record_user=False)
store.elevated_add(ELEV, OWNER)


async def main():
    # (a) Bare bot-link list from a member with a username.
    fb = FakeBot(); bot.LINK_ONLY_TRACKER.reset()
    await post(fb, user(SPAM, "spamuser"), GA, INCIDENT_LINKS, mid=20)
    check("(a) message deleted", (GA, 20) in fb.deleted)
    check("(a) banned in the group", (GA, SPAM) in fb.bans)
    check("(a) ban propagated to mod-list group", (GB, SPAM) in fb.bans)
    check("(a) ban propagated to registry group", (GC, SPAM) in fb.bans)
    dms = owner_dms(fb)
    check("(a) one evidence DM to the owner", len(dms) == 1)
    if dms:
        _cid, text, kwargs = dms[0]
        kb = kwargs.get("reply_markup")
        btn = kb.inline_keyboard[0][0] if kb else None
        check("(a) DM names the offender + group",
              "spamuser" in text and "555" in text and "Terra Luna Classic Chat" in text)
        check("(a) DM shows what they posted", "@gAm0kiGk8bot" in text)
        check("(a) DM button is the report link (username)",
              btn is not None and btn.text == "🚩 Report them"
              and btn.url == "https://t.me/spamuser")

    # (a2) Same, offender without a username -> tg:// button.
    fb = FakeBot(); bot.LINK_ONLY_TRACKER.reset()
    await post(fb, user(SPAM2), GA, INCIDENT_LINKS, mid=21)
    dms = owner_dms(fb)
    btn = None
    if dms:
        kb = dms[0][2].get("reply_markup")
        btn = kb.inline_keyboard[0][0] if kb else None
    check("(a2) banned too", (GA, SPAM2) in fb.bans)
    check("(a2) DM button falls back to tg:// user link",
          btn is not None and btn.url == f"tg://user?id={SPAM2}")

    # (b) Two link-only posts inside 10 minutes.
    fb = FakeBot(); bot.LINK_ONLY_TRACKER.reset()
    await post(fb, user(MEMBER), GA, "https://t.me/somechannel", mid=30)
    check("(b) first link-only post is left alone",
          fb.bans == [] and fb.deleted == [])
    await post(fb, user(MEMBER), GA, "https://example.com/chart", mid=31)
    check("(b) second link-only post bans", (GA, MEMBER) in fb.bans)
    check("(b) both messages deleted", (GA, 30) in fb.deleted and (GA, 31) in fb.deleted)

    # (c) Payment-scam bait with a contact.
    fb = FakeBot(); bot.LINK_ONLY_TRACKER.reset()
    await post(fb, user(SPAM, "YLzhangwei888"), GA, INCIDENT_AD, mid=40)
    check("(c) scam ad poster banned", (GA, SPAM) in fb.bans)
    check("(c) ad deleted", (GA, 40) in fb.deleted)
    check("(c) evidence DM sent", len(owner_dms(fb)) == 1)

    # Exemptions: admin, owner, elevated, the bot itself.
    fb = FakeBot(); fb.admins.add((GA, ADMIN)); bot.LINK_ONLY_TRACKER.reset()
    await post(fb, user(ADMIN), GA, INCIDENT_LINKS, mid=50)
    check("group admin is exempt", fb.bans == [] and fb.deleted == [])
    fb = FakeBot(); bot.LINK_ONLY_TRACKER.reset()
    await post(fb, user(OWNER), GA, INCIDENT_LINKS, mid=51)
    check("owner is exempt", fb.bans == [] and fb.deleted == [])
    fb = FakeBot(); bot.LINK_ONLY_TRACKER.reset()
    await post(fb, user(ELEV), GA, INCIDENT_LINKS, mid=52)
    check("elevated user is exempt", fb.bans == [] and fb.deleted == [])
    fb = FakeBot(); bot.LINK_ONLY_TRACKER.reset()
    await post(fb, user(BOT_ID, "LuncAssistantBot", is_bot=True), GA, INCIDENT_LINKS, mid=53)
    check("the bot itself is exempt", fb.bans == [] and fb.deleted == [])

    # Propagation skips groups where the bot lacks rights, silently.
    fb = FakeBot(); fb.fail_bans.add(GB); bot.LINK_ONLY_TRACKER.reset()
    await post(fb, user(SPAM, "spamuser"), GA, INCIDENT_LINKS, mid=60)
    check("propagation failure is silent, home ban + DM still happen",
          (GA, SPAM) in fb.bans and (GB, SPAM) not in fb.bans
          and len(owner_dms(fb)) == 1)

    # Normal traffic is untouched.
    fb = FakeBot(); bot.LINK_ONLY_TRACKER.reset()
    await post(fb, user(MEMBER), GA, "look at this chart https://example.com/c it is wild", mid=70)
    check("normal message with a link is untouched", fb.bans == [] and fb.deleted == [])

    # AI linkage: spammer's logged link spam + a links-only AI output.
    fb = FakeBot(); bot.LINK_ONLY_TRACKER.reset()
    store.log_message(GA, SPAM, "U555 (@spamuser)", "@gAm0kiGk8bot @gbrcm9dfdbot", 777)
    m = FakeMsg(chat(GA), user(SPAM, "spamuser"), text="/summary", mid=80)
    await bot._send_ai_text(upd(m, user(SPAM, "spamuser")), INCIDENT_LINKS, ctx(fb))
    check("ai-launder: invoker banned", (GA, SPAM) in fb.bans)
    check("ai-launder: their logged spam deleted", (GA, 777) in fb.deleted)
    check("ai-launder: evidence DM sent", len(owner_dms(fb)) == 1)

    # AI linkage control: a user whose logged history is clean chat,
    # same killed output -> nothing. (Fresh id: MEMBER's earlier
    # tracker-test posts are legitimately link-only history.)
    fb = FakeBot(); bot.LINK_ONLY_TRACKER.reset()
    CLEAN = 558
    store.log_message(GA, CLEAN, "U558", "hello everyone, nice day", 778)
    m = FakeMsg(chat(GA), user(CLEAN), text="/summary", mid=81)
    await bot._send_ai_text(upd(m, user(CLEAN)), INCIDENT_LINKS, ctx(fb))
    check("ai-launder control: clean user untouched", fb.bans == [] and fb.deleted == [])


asyncio.run(main())
print(f"\n{_total[0] - len(fails)}/{_total[0]} passed" if not fails else f"\nFAILED: {fails}")
sys.exit(1 if fails else 0)
