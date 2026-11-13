"""Tests for owner-only /del (2026-11-13): the owner replies to any
message in a group with /del and the bot deletes that message (its
own mistaken posts, spam). Non-owners are ignored silently; a failed
delete earns the owner one brief reply.

Run: python3 test_del.py"""
import asyncio
import os
import sys
import tempfile
import types

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["OWNER_TELEGRAM_ID"] = "999"

# --- Dependency stubs (same pattern as test_filter.py) ---
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

OWNER, MEMBER = 999, 555
GROUP = -100111

fails = []


def check(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        fails.append(name)


def user(uid):
    return types.SimpleNamespace(id=uid, full_name="U", username=None, is_bot=False)


class FakeMsg:
    def __init__(self, usr, reply_to=None, fail_delete=False):
        self.chat = types.SimpleNamespace(id=GROUP, type="supergroup")
        self.from_user = usr
        self.text = "/del"
        self.reply_to_message = reply_to
        self.replies = []
        self.deleted = 0
        self.fail_delete = fail_delete

    async def delete(self):
        if self.fail_delete:
            raise RuntimeError("message too old")
        self.deleted += 1

    async def reply_text(self, text, **kwargs):
        self.replies.append(text)


def upd(msg, usr):
    return types.SimpleNamespace(
        message=msg, effective_message=msg,
        effective_chat=msg.chat, effective_user=usr)


def ctx():
    return types.SimpleNamespace(bot=None, args=[])


async def main():
    # Owner replies /del to a message -> the target is deleted.
    target = FakeMsg(user(MEMBER))
    cmd = FakeMsg(user(OWNER), reply_to=target)
    await bot.on_del(upd(cmd, user(OWNER)), ctx())
    check("owner /del deletes the replied-to message", target.deleted == 1)
    check("owner /del stays quiet on success", cmd.replies == [])

    # Non-owner /del -> nothing happens, silently.
    target2 = FakeMsg(user(MEMBER))
    cmd2 = FakeMsg(user(MEMBER), reply_to=target2)
    await bot.on_del(upd(cmd2, user(MEMBER)), ctx())
    check("non-owner /del deletes nothing", target2.deleted == 0)
    check("non-owner /del is ignored silently", cmd2.replies == [])

    # Owner /del with no replied-to message -> no crash, no reply.
    cmd3 = FakeMsg(user(OWNER), reply_to=None)
    await bot.on_del(upd(cmd3, user(OWNER)), ctx())
    check("owner /del without a reply target does nothing", cmd3.replies == [])

    # Delete fails (too old / no permission) -> owner gets one brief reply.
    target4 = FakeMsg(user(MEMBER), fail_delete=True)
    cmd4 = FakeMsg(user(OWNER), reply_to=target4)
    await bot.on_del(upd(cmd4, user(OWNER)), ctx())
    check("failed delete tells the owner", len(cmd4.replies) == 1 and "Couldn't delete" in cmd4.replies[0])


asyncio.run(main())
print(f"\n{6 - len(fails)}/6 passed" if not fails else f"\nFAILED: {fails}")
sys.exit(1 if fails else 0)
