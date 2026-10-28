"""Tests for the per-group phrase filter (2026-10-27): /muteword add
deletes matching messages IN THAT GROUP ONLY and mutes the sender
24h — no ban, independent of /protect, global blacklist untouched.
Run: python3 test_filter.py"""
import asyncio
import datetime
import os
import sys
import tempfile
import types

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["OWNER_TELEGRAM_ID"] = "999"

# --- Dependency stubs (same pattern as test_freegames_effective_message.py) ---
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

import bot
import store

fails = []


def check(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        fails.append(name)


# --- Fakes ---
OWNER, ELEV, ADMIN, MEMBER, MEMBER2 = 999, 888, 777, 555, 556
GA, GB, GC = -100111, -100222, -100333  # A/B unprotected, C protected


def user(uid, name):
    return types.SimpleNamespace(id=uid, full_name=name, username=None, is_bot=False)


def chat(cid):
    return types.SimpleNamespace(id=cid, type="supergroup")


class FakeMsg:
    def __init__(self, ch, usr, text=None, caption=None, mid=1):
        self.chat, self.from_user = ch, usr
        self.text, self.caption = text, caption
        self.message_id = mid
        self.entities = []
        self.caption_entities = []
        self.deleted = 0
        self.replies = []

    async def delete(self):
        self.deleted += 1

    async def reply_text(self, text, **kwargs):
        self.replies.append(text)


class FakeBot:
    def __init__(self):
        self.admins = set()
        self.restricts = []
        self.bans = []
        self.sent = []

    def reset(self):
        self.restricts, self.bans, self.sent = [], [], []

    async def get_chat_member(self, chat_id, user_id):
        return types.SimpleNamespace(
            status="administrator" if (chat_id, user_id) in self.admins else "member")

    async def restrict_chat_member(self, chat_id, user_id, permissions=None, until_date=None):
        self.restricts.append({"chat": chat_id, "user": user_id,
                               "permissions": permissions, "until": until_date})

    async def ban_chat_member(self, chat_id, user_id):
        self.bans.append(("ban", chat_id, user_id))

    async def unban_chat_member(self, chat_id, user_id, only_if_banned=False):
        self.bans.append(("unban", chat_id, user_id))

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append((chat_id, text))

    async def get_me(self):
        return types.SimpleNamespace(username="LuncAssistantBot")


fb = FakeBot()
fb.admins.add((GA, ADMIN))
fb.admins.add((GC, ADMIN))

store.elevated_add(ELEV, OWNER)
store.mod_request_group(GC, "Group C", OWNER)
store.mod_approve_group(GC)
store.blacklist_add("blackcoin", OWNER)


def upd(msg, usr):
    return types.SimpleNamespace(
        message=msg, effective_message=msg,
        effective_chat=msg.chat, effective_user=usr, edited_message=None)


def ctx(args=None):
    return types.SimpleNamespace(bot=fb, args=args or [])


async def run_filter(usr, cid, args):
    m = FakeMsg(chat(cid), usr, text="/muteword")
    await bot.on_muteword(upd(m, usr), ctx(args))
    return m.replies[-1] if m.replies else ""


async def post(usr, cid, text, mid=1):
    m = FakeMsg(chat(cid), usr, text=text, mid=mid)
    await bot.on_message(upd(m, usr), ctx())
    return m


async def main():
    # --- Permission gating ---
    r = await run_filter(user(MEMBER, "Member"), GA, ["add", "this", "is", "a", "scam"])
    check("member cannot add a phrase", "Only this group's admins" in r)
    check("phrase not stored after denied add", bot._filter_phrases(GA) == [])

    r = await run_filter(user(ADMIN, "Admin"), GA, ["add", "This", "Is", "A", "Scam"])
    check("group admin can add", "✅" in r)
    check("phrase stored lowercase", bot._filter_phrases(GA) == ["this is a scam"])

    r = await run_filter(user(ADMIN, "Admin"), GA, ["add", "this", "is", "a", "scam"])
    check("duplicate add refused", "already" in r and bot._filter_phrases(GA) == ["this is a scam"])

    r = await run_filter(user(OWNER, "Owner"), GA, ["add", "ab"])
    check("phrase under 3 chars refused", "at least 3 characters" in r)

    r = await run_filter(user(ELEV, "Elev"), GB, ["add", "rug", "pull"])
    check("elevated user can add in another group", "✅" in r and bot._filter_phrases(GB) == ["rug pull"])
    await run_filter(user(OWNER, "Owner"), GB, ["remove", "rug", "pull"])
    check("owner can remove again (group B back to empty)", bot._filter_phrases(GB) == [])

    # --- Status / list ---
    r = await run_filter(user(ADMIN, "Admin"), GA, [])
    check("bare /muteword shows ON + phrase + how-to",
          "ON" in r and "this is a scam" in r and "/muteword add" in r)
    r = await run_filter(user(ADMIN, "Admin"), GA, ["list"])
    check("/muteword list shows the phrase", "this is a scam" in r)
    r = await run_filter(user(OWNER, "Owner"), GA, ["remove", "not", "there"])
    check("removing a missing phrase says so", "isn't on this group's filter" in r)

    # --- Enforcement: text message, unprotected group ---
    fb.reset()
    m = await post(user(MEMBER, "Member"), GA, "guys, this is a scam!!", mid=10)
    check("matching message deleted", m.deleted == 1)
    check("sender restricted exactly once", len(fb.restricts) == 1)
    if fb.restricts:
        rc = fb.restricts[0]
        delta = rc["until"] - datetime.datetime.now(datetime.timezone.utc)
        check("restrict targets the sender in that group", rc["user"] == MEMBER and rc["chat"] == GA)
        check("restrict uses NO_PERMS", rc["permissions"] is bot.NO_PERMS)
        check("mute lasts ~24h", datetime.timedelta(hours=23, minutes=50) < delta <= datetime.timedelta(hours=24, minutes=5))
    check("filter never bans", fb.bans == [])
    check("in-group notice names user, duration, phrase",
          any(c == GA and "Member" in t and "24 hours" in t and "'this is a scam'" in t for c, t in fb.sent))
    check("mod log records the filter mute",
          any(row["action"] == "filter mute" and row["target"] == MEMBER and row["chat_id"] == GA
              for row in store.mod_log_recent(50)))

    # --- Per-group isolation + non-match ---
    fb.reset()
    m = await post(user(MEMBER, "Member"), GB, "guys, this is a scam!!", mid=11)
    check("same text untouched in a group without the phrase", m.deleted == 0 and fb.restricts == [])
    m = await post(user(MEMBER, "Member"), GA, "this project is great", mid=12)
    check("non-matching message untouched", m.deleted == 0 and fb.restricts == [])

    # --- Exemptions ---
    for usr, label in ((ADMIN, "group admin"), (OWNER, "owner"), (ELEV, "elevated user")):
        fb.reset()
        m = await post(user(usr, label), GA, "this is a scam, quoting a troll", mid=13)
        check(f"{label} is exempt (not even deleted)", m.deleted == 0 and fb.restricts == [])

    # --- Captions + edits (unprotected group) ---
    fb.reset()
    m = FakeMsg(chat(GA), user(MEMBER, "Member"), caption="proof: THIS IS A SCAM", mid=14)
    await bot.on_media_message(upd(m, user(MEMBER, "Member")), ctx())
    check("caption match (any case) deletes + mutes", m.deleted == 1 and len(fb.restricts) == 1)

    fb.reset()
    em = FakeMsg(chat(GA), user(MEMBER, "Member"), text="edited to add: this is a scam", mid=15)
    eu = types.SimpleNamespace(edited_message=em, message=None,
                               effective_chat=em.chat, effective_user=em.from_user,
                               effective_message=em)
    await bot.on_edited_message(eu, ctx())
    check("edited-message match deletes + mutes", em.deleted == 1 and len(fb.restricts) == 1)

    # --- Protected group: blacklist still wins, no double punishment ---
    await run_filter(user(OWNER, "Owner"), GC, ["add", "moon", "juice"])
    fb.reset()
    m = await post(user(MEMBER2, "Member2"), GC, "blackcoin and moon juice", mid=16)
    check("protected + both match: blacklist removal fires",
          ("ban", GC, MEMBER2) in fb.bans and m.deleted == 1)
    check("protected + both match: filter does NOT also mute", fb.restricts == [])

    fb.reset()
    m = await post(user(MEMBER2, "Member2"), GC, "moon juice for everyone", mid=17)
    check("protected + filter-only match: delete + 24h mute, no ban",
          m.deleted == 1 and len(fb.restricts) == 1 and fb.bans == [])

    fb.reset()
    m = await post(user(MEMBER2, "Member2"), GC, "blackcoin giveaway", mid=18)
    check("protected + blacklist-only match: removed as before (blacklist untouched)",
          ("ban", GC, MEMBER2) in fb.bans and fb.restricts == [])

    # --- Remove restores normal flow ---
    r = await run_filter(user(ADMIN, "Admin"), GA, ["remove", "this", "is", "a", "scam"])
    check("admin can remove the phrase", "Removed" in r and bot._filter_phrases(GA) == [])
    fb.reset()
    m = await post(user(MEMBER, "Member"), GA, "this is a scam", mid=19)
    check("after remove, the same text flows normally", m.deleted == 0 and fb.restricts == [])

    # --- Private chat ---
    pm = FakeMsg(types.SimpleNamespace(id=MEMBER, type="private"), user(MEMBER, "Member"), text="/muteword")
    pu = types.SimpleNamespace(message=pm, effective_message=pm,
                               effective_chat=pm.chat, effective_user=pm.from_user,
                               edited_message=None)
    await bot.on_muteword(pu, ctx(["list"]))
    check("/muteword in DM points at groups", bool(pm.replies) and "in a group" in pm.replies[-1])


asyncio.run(main())

print()
print("FAILURES:", fails if fails else "none")
sys.exit(1 if fails else 0)
