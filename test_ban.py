"""Tests for /ban (2026-11-21) + the Tianci network's new handles on
the permanent name blocklist.

/ban: reply to a message in a group -> its sender is banned from THIS
group only and the message is deleted. Gate: owner, elevated user, or
an admin of THIS chat (live get_chat_member check, fail closed).

Blocklist: the four new handles from the 2026-11-21 sighting in the
"Lunc Global Marketing Team" group (@xxin7 the distribution account,
plus its fresh bots @ll9cP1mbot, @lO_mqfxebot, @iowhPr5RZwbot) must
match case-insensitively once filed, land the ban+delete strike, and
fail safe (no raise, no harm) when the bot lacks admin rights.

Run: python3 test_ban.py"""
import asyncio
import os
import sys
import tempfile
import types

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["OWNER_TELEGRAM_ID"] = "999"

# --- Dependency stubs (same pattern as test_blocklist.py) ---
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

OWNER, ELEV, MEMBER, ADMIN, SPAMMER = 999, 777, 555, 444, 31337
BOT_ID = 4242
GROUP = -100777

fails = []


def check(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        fails.append(name)


def user(uid, username=None):
    return types.SimpleNamespace(id=uid, full_name=f"U{uid}", username=username,
                                 is_bot=False)


def chat(cid, ctype="supergroup"):
    return types.SimpleNamespace(id=cid, type=ctype, title="Test Group")


class FakeMsg:
    def __init__(self, ch, usr, text="", mid=1):
        self.chat, self.from_user = ch, usr
        self.text = text
        self.message_id = mid
        self.entities = []
        self.reply_to_message = None
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append(text)


class FakeBot:
    """admins: set of user ids reported as chat administrators.
    fail: ban/delete raise (bot lacks rights)."""

    def __init__(self, admins=(), fail=False):
        self.id = BOT_ID
        self.admins = set(admins)
        self.fail = fail
        self.bans = []
        self.deleted = []
        self.sent = []

    async def ban_chat_member(self, chat_id, user_id):
        if self.fail:
            raise RuntimeError("not enough rights")
        self.bans.append((chat_id, user_id))

    async def unban_chat_member(self, chat_id, user_id, only_if_banned=False):
        pass

    async def delete_message(self, chat_id, message_id):
        if self.fail:
            raise RuntimeError("not enough rights")
        self.deleted.append((chat_id, message_id))

    async def get_chat_member(self, chat_id, user_id):
        return types.SimpleNamespace(
            status="administrator" if user_id in self.admins else "member")

    async def get_me(self):
        return types.SimpleNamespace(username="LuncAssistantBot")

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append((chat_id, text, kwargs))


def upd(msg, usr):
    return types.SimpleNamespace(
        message=msg, effective_message=msg,
        effective_chat=msg.chat, effective_user=usr, edited_message=None)


def ctx(fb, args=()):
    return types.SimpleNamespace(bot=fb, args=list(args))


# --- The four new handles: filing + case handling ---------------------
for raw, norm in (("@XXin7", "xxin7"), ("@ll9cP1mbot", "ll9cp1mbot"),
                  ("@lO_mqfxebot", "lo_mqfxebot"),
                  ("@iowhPr5RZwbot", "iowhpr5rzwbot")):
    check(f"blocklist: {raw} files + normalizes to {norm}",
          store.blockname_add(raw, OWNER, "Tianci scam network") is True
          and store.blockname_get(norm) is not None
          and store.blockname_get(raw.upper()) is not None)


async def main():
    g = chat(GROUP)

    # --- Blocklist strike: mixed-case sighting -> ban + delete --------
    fb = FakeBot()
    spammer = user(6001, "XXIN7")          # filed as xxin7
    msg = FakeMsg(g, spammer, "USDT OTC, contact me", mid=50)
    await bot._blocklist_check(upd(msg, spammer), ctx(fb))
    check("blocklist: sighting of filed handle bans sender in the group",
          (GROUP, 6001) in fb.bans)
    check("blocklist: sighting deletes the triggering message",
          (GROUP, 50) in fb.deleted)

    # --- Blocklist no-op safety: bot without rights -> no raise -------
    fb2 = FakeBot(fail=True)
    spammer2 = user(6002, "ll9cP1mbot")
    msg2 = FakeMsg(g, spammer2, "spam", mid=51)
    try:
        await bot._blocklist_check(upd(msg2, spammer2), ctx(fb2))
        no_raise = True
    except Exception:
        no_raise = False
    check("blocklist: no admin rights -> strike fails safe, nothing recorded",
          no_raise and fb2.bans == [] and fb2.deleted == [])

    # --- A normal member is untouched ---------------------------------
    fb3 = FakeBot()
    normal = user(6003, "regularmember")
    msg3 = FakeMsg(g, normal, "hello", mid=52)
    await bot._blocklist_check(upd(msg3, normal), ctx(fb3))
    check("blocklist: unlisted user untouched",
          fb3.bans == [] and fb3.deleted == [])

    # --- /ban: plain member is refused (fail closed) ------------------
    fb = FakeBot()
    spam_msg = FakeMsg(g, user(SPAMMER, "spambot"), "buy USDT", mid=60)
    cmd = FakeMsg(g, user(MEMBER), "/ban", mid=61)
    cmd.reply_to_message = spam_msg
    await bot.on_ban(upd(cmd, user(MEMBER)), ctx(fb))
    check("/ban: plain member refused, no ban, no delete",
          fb.bans == [] and fb.deleted == []
          and any("Only the owner" in r for r in cmd.replies))

    # --- /ban: group admin (not owner, group NOT protected) works -----
    fb = FakeBot(admins={ADMIN})
    cmd = FakeMsg(g, user(ADMIN), "/ban scam", mid=62)
    cmd.reply_to_message = spam_msg
    await bot.on_ban(upd(cmd, user(ADMIN)), ctx(fb, ["scam"]))
    check("/ban: group admin bans the replied sender from this group",
          fb.bans == [(GROUP, SPAMMER)])
    check("/ban: group admin's /ban deletes the replied message",
          fb.deleted == [(GROUP, 60)])

    # --- /ban: owner works without being a chat admin -----------------
    fb = FakeBot()
    cmd = FakeMsg(g, user(OWNER), "/ban", mid=63)
    cmd.reply_to_message = spam_msg
    await bot.on_ban(upd(cmd, user(OWNER)), ctx(fb))
    check("/ban: owner bans without chat-admin status",
          fb.bans == [(GROUP, SPAMMER)] and fb.deleted == [(GROUP, 60)])

    # --- /ban: no reply -> usage, nothing happens ----------------------
    fb = FakeBot(admins={ADMIN})
    cmd = FakeMsg(g, user(ADMIN), "/ban", mid=64)
    await bot.on_ban(upd(cmd, user(ADMIN)), ctx(fb))
    check("/ban: no reply target -> usage reply, no ban",
          fb.bans == [] and any("Usage" in r for r in cmd.replies))

    # --- /ban: the owner can never be the target -----------------------
    fb = FakeBot(admins={ADMIN})
    owner_msg = FakeMsg(g, user(OWNER), "hi", mid=65)
    cmd = FakeMsg(g, user(ADMIN), "/ban", mid=66)
    cmd.reply_to_message = owner_msg
    await bot.on_ban(upd(cmd, user(ADMIN)), ctx(fb))
    check("/ban: target=owner refused",
          fb.bans == [] and any("can't be banned" in r for r in cmd.replies))

    # --- /ban: bot lacks rights -> honest failure reply, no delete -----
    fb = FakeBot(admins={ADMIN}, fail=True)
    cmd = FakeMsg(g, user(ADMIN), "/ban", mid=67)
    cmd.reply_to_message = spam_msg
    await bot.on_ban(upd(cmd, user(ADMIN)), ctx(fb))
    check("/ban: ban API failure -> 'Couldn't ban' reply, message kept",
          fb.deleted == [] and any("Couldn't ban" in r for r in cmd.replies))

    # --- /ban: DMs are refused ------------------------------------------
    fb = FakeBot()
    dm = chat(OWNER, "private")
    cmd = FakeMsg(dm, user(OWNER), "/ban", mid=68)
    cmd.reply_to_message = FakeMsg(dm, user(SPAMMER), "spam", mid=69)
    await bot.on_ban(upd(cmd, user(OWNER)), ctx(fb))
    check("/ban: private chat refused", fb.bans == [])


asyncio.run(main())
print()
if fails:
    print(f"{len(fails)} FAILURES:", fails)
    sys.exit(1)
print("ALL PASS")
