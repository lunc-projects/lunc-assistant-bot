"""Native Telegram Games tests.

The VM does not have the bot's Railway-only dependencies installed, so this
file installs small telegram/httpx stubs before importing bot.py. It checks
the short-name mapping, the group sendGame path with a per-game link
fallback, the Play-button callback URL, and inline game results.
Run: python3 test_games.py
"""
import asyncio
import os
import sys
import tempfile
import types

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")

# --- Dependency stubs (only the pieces bot.py touches at import/use here) ---
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
sys.modules["telegram.ext"] = ext

import bot

fails = []


def check(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        fails.append(name)


check("three native games", [g[0] for g in bot.TELEGRAM_GAMES] == ["neonrush", "solitaire", "hoops"])
check("short names map to the live pages",
      bot.GAME_URL_BY_SHORT_NAME["neonrush"].endswith("/neon-rush/")
      and bot.GAME_URL_BY_SHORT_NAME["solitaire"].endswith("/solitaire/")
      and bot.GAME_URL_BY_SHORT_NAME["hoops"].endswith("/hoops/"))


class FakeBot:
    def __init__(self):
        self.sent_games = []

    async def send_game(self, chat_id, game_short_name):
        self.sent_games.append((chat_id, game_short_name))
        if game_short_name == "hoops":
            raise RuntimeError("game not registered yet")


class FakeMessage:
    def __init__(self):
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append((text, kwargs))


async def group_case():
    message = FakeMessage()
    update = types.SimpleNamespace(
        effective_chat=types.SimpleNamespace(id=-100123, type="supergroup"),
        message=message,
    )
    fake_bot = FakeBot()
    await bot.on_games(update, types.SimpleNamespace(bot=fake_bot))
    check("group tries every native game card",
          fake_bot.sent_games == [(-100123, "neonrush"), (-100123, "solitaire"), (-100123, "hoops")])
    check("only the failed game falls back to a link", len(message.replies) == 1)
    if message.replies:
        rows = message.replies[0][1]["reply_markup"].inline_keyboard
        flat = [b for row in rows for b in row]
        check("fallback has just the Hoops link", len(flat) == 1 and flat[0].url == bot.HOOPS_URL)


asyncio.run(group_case())


class FakeCallback:
    def __init__(self, short_name):
        self.game_short_name = short_name
        self.answer_args = None

    async def answer(self, **kwargs):
        self.answer_args = kwargs


async def callback_case():
    q = FakeCallback("solitaire")
    await bot.on_game_callback(types.SimpleNamespace(callback_query=q), None)
    check("Play callback returns the Solitaire URL", q.answer_args == {"url": bot.SOLITAIRE_URL})
    q2 = FakeCallback("unknown")
    await bot.on_game_callback(types.SimpleNamespace(callback_query=q2), None)
    check("unknown game gets an alert", q2.answer_args.get("show_alert") is True)


asyncio.run(callback_case())


class FakeInlineQuery:
    def __init__(self, query):
        self.query = query
        self.answer_args = None

    async def answer(self, results, **kwargs):
        self.answer_args = ([r.game_short_name for r in results], kwargs)


async def inline_case():
    iq = FakeInlineQuery("")
    await bot.on_inline_query(types.SimpleNamespace(inline_query=iq), None)
    check("empty inline query offers all three games", iq.answer_args[0] == ["neonrush", "solitaire", "hoops"])
    iq2 = FakeInlineQuery("hoop")
    await bot.on_inline_query(types.SimpleNamespace(inline_query=iq2), None)
    check("inline search filters by name", iq2.answer_args[0] == ["hoops"])


asyncio.run(inline_case())

print()
print("FAILURES:", fails if fails else "none")
sys.exit(1 if fails else 0)
