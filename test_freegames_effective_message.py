"""Reproduction for the Oct 26 20:29 UTC owner alert:

    Bot issue — message '/freegames'
    AttributeError: 'NoneType' object has no attribute 'reply_text'

Cause: the update that carried /freegames had an effective_message but
update.message was None (edited-message / channel-post shaped update —
PTB's CommandHandler fires on effective_message). on_games replied via
update.message.reply_text and crashed. The fix replies via
update.effective_message.reply_text everywhere in bot.py.

This test feeds on_games fake updates with message=None and an
effective_message set — group-shaped and DM-shaped — plus a normal
message-shaped update to confirm unchanged behavior.
Run: python3 test_freegames_effective_message.py
"""
import asyncio
import os
import sys
import tempfile
import types

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")

# --- Dependency stubs (same pattern as test_games.py) ---
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

fails = []


def check(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        fails.append(name)


class FakeMessage:
    def __init__(self, text="/freegames"):
        self.text = text
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append((text, kwargs))


async def fake_fetch_board(url):
    return None


bot._fetch_board = fake_fetch_board


async def main():
    # --- BEFORE: the pre-fix expression on this update shape crashes ---
    probe = types.SimpleNamespace(message=None, effective_message=FakeMessage())
    try:
        probe.message.reply_text  # the old on_games access pattern
        check("before: update.message.reply_text raises AttributeError", False)
    except AttributeError as e:
        check("before: update.message.reply_text raises AttributeError",
              "'NoneType' object has no attribute 'reply_text'" in str(e))

    # --- AFTER, group-shaped: message=None, effective_message set ---
    gmsg = FakeMessage()
    gupdate = types.SimpleNamespace(
        message=None,
        effective_message=gmsg,
        effective_chat=types.SimpleNamespace(id=-100123, type="supergroup"),
    )
    await bot.on_games(gupdate, types.SimpleNamespace(bot=None))
    check("after: group /freegames with message=None replies cleanly",
          len(gmsg.replies) == 1 and "Pick a game" in gmsg.replies[0][0])

    # --- AFTER, DM-shaped: message=None, effective_message set ---
    dmsg = FakeMessage()
    dupdate = types.SimpleNamespace(
        message=None,
        effective_message=dmsg,
        effective_chat=types.SimpleNamespace(id=4242, type="private"),
    )
    await bot.on_games(dupdate, types.SimpleNamespace(bot=None))
    ok = len(dmsg.replies) == 1
    if ok:
        _text, kwargs = dmsg.replies[0]
        rows = kwargs["reply_markup"].inline_keyboard
        flat = [b for row in rows for b in row]
        ok = len(flat) == 20 and all(b.web_app is not None for b in flat)
        ok = ok and any(b.web_app.url == bot.CLIMB_URL for b in flat)
    check("after: DM /freegames with message=None replies with 20 game buttons", ok)

    # --- Normal message-shaped update: behavior unchanged ---
    nmsg = FakeMessage()
    nupdate = types.SimpleNamespace(
        message=nmsg,
        effective_message=nmsg,
        effective_chat=types.SimpleNamespace(id=-100123, type="supergroup"),
    )
    await bot.on_games(nupdate, types.SimpleNamespace(bot=None))
    check("normal group /freegames still replies with the picker",
          len(nmsg.replies) == 1 and "Pick a game" in nmsg.replies[0][0])


asyncio.run(main())

print()
print("FAILURES:", fails if fails else "none")
sys.exit(1 if fails else 0)
