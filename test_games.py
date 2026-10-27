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


ALL_SHORT_NAMES = ["neonrush", "solitaire", "hoops", "Penalty", "Darts", "LunaBlocks",
                   "Lunagolf", "LunaDefender", "LunaTower", "LunaSnake", "LunaFlap",
                   "LunaPinball", "LunaRacer", "LunaCannon", "LunaWhack", "LunaRider",
                   "LunaPool", "ZOMBIEDEFENSE", "LunaBreakout", "LUNACLIMB"]
check("twenty native games", [g[0] for g in bot.TELEGRAM_GAMES] == ALL_SHORT_NAMES)
check("short names map to the live pages",
      bot.GAME_URL_BY_SHORT_NAME["neonrush"].endswith("/neon-rush/")
      and bot.GAME_URL_BY_SHORT_NAME["solitaire"].endswith("/solitaire/")
      and bot.GAME_URL_BY_SHORT_NAME["hoops"].endswith("/hoops/")
      and bot.GAME_URL_BY_SHORT_NAME["Penalty"].endswith("/penalty/")
      and bot.GAME_URL_BY_SHORT_NAME["Darts"].endswith("/darts/")
      and bot.GAME_URL_BY_SHORT_NAME["LunaBlocks"].endswith("/blocks/")
      and bot.GAME_URL_BY_SHORT_NAME["LUNACLIMB"] == bot.CLIMB_URL
      and bot.GAME_URL_BY_SHORT_NAME["LUNACLIMB"].endswith("/climb/"))
check("climb board fetch URL is the router endpoint for game=climb",
      dict((s, a) for s, _t, a in bot.GAME_BOARD_APIS)["LUNACLIMB"]
      == "https://frg-fight-club.vercel.app/api/luna-games?game=climb")
check("games text describes Luna Climb", "LUNA CLIMB" in bot.GAMES_TEXT)


class FakeBot:
    def __init__(self):
        self.sent_games = []
        self.sent_game_kwargs = []
        self.sent_messages = []

    async def send_game(self, chat_id, game_short_name, **kwargs):
        self.sent_games.append((chat_id, game_short_name))
        self.sent_game_kwargs.append(kwargs)
        if game_short_name == "hoops":
            raise RuntimeError("game not registered yet")

    async def send_message(self, chat_id, text, **kwargs):
        self.sent_messages.append((chat_id, text, kwargs))


class FakeMessage:
    def __init__(self):
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append((text, kwargs))


async def fake_fetch_board(url):
    if "neon-rush" in url:
        return {"all": [{"name": "Tom", "score": 1192}, {"name": "Ace", "score": 900}], "week": []}
    if "solitaire" in url:
        return {"all": [], "week": []}
    if "penalty" in url:
        return {"all": [{"name": "Zed", "score": 500}], "week": []}
    return None


bot._fetch_board = fake_fetch_board


async def group_case():
    message = FakeMessage()
    update = types.SimpleNamespace(
        effective_chat=types.SimpleNamespace(id=-100123, type="supergroup"),
        message=message,
        effective_message=message,
    )
    fake_bot = FakeBot()
    await bot.on_games(update, types.SimpleNamespace(bot=fake_bot))
    check("group /games posts NO game cards directly", fake_bot.sent_games == [])
    check("group /games is a single picker post", len(message.replies) == 1)
    if message.replies:
        text, kwargs = message.replies[0]
        rows = kwargs["reply_markup"].inline_keyboard
        flat = [b for row in rows for b in row]
        check("picker has one button per game",
              [b.callback_data for b in flat] == [f"pick:{s}" for s in ALL_SHORT_NAMES])
        check("picker text shows the Neon leader", "Tom 1,192" in text)
        check("picker text marks the empty Solitaire board", text.count("no scores yet") == 1)
        check("picker text admits an unavailable board", "leaderboard unavailable right now" in text)
        check("picker text shows the Penalty leader", "Zed 500" in text)
        check("picker text titles all twenty boards",
              all(t in text for _s, t, _a in bot.GAME_BOARD_APIS))


class FakePick:
    def __init__(self, data, thread_id=None):
        self.data = data
        self.game_short_name = None
        self.message = types.SimpleNamespace(chat=types.SimpleNamespace(id=-100123),
                                             message_thread_id=thread_id)
        self.answer_args = None

    async def answer(self, **kwargs):
        self.answer_args = kwargs


async def pick_case():
    fake_bot = FakeBot()
    q = FakePick("pick:solitaire")
    await bot.on_pick_callback(types.SimpleNamespace(callback_query=q),
                                 types.SimpleNamespace(bot=fake_bot))
    check("pick posts only the chosen game card", fake_bot.sent_games == [(-100123, "solitaire")])
    check("successful pick sends no link message", fake_bot.sent_messages == [])
    q2 = FakePick("pick:hoops")
    await bot.on_pick_callback(types.SimpleNamespace(callback_query=q2),
                                 types.SimpleNamespace(bot=fake_bot))
    check("failed pick falls back to that game's link",
          len(fake_bot.sent_messages) == 1
          and fake_bot.sent_messages[0][2]["reply_markup"].inline_keyboard[0][0].url == bot.HOOPS_URL)
    check("non-topic pick passes no thread id",
          fake_bot.sent_game_kwargs[0] == {} and "message_thread_id" not in fake_bot.sent_messages[0][2])
    # Forum topic: the picker was tapped inside topic 777 — the card (and the
    # fallback link) must carry message_thread_id so they post in that topic.
    q3 = FakePick("pick:solitaire", thread_id=777)
    await bot.on_pick_callback(types.SimpleNamespace(callback_query=q3),
                               types.SimpleNamespace(bot=fake_bot))
    check("topic pick passes the thread id to send_game",
          fake_bot.sent_game_kwargs[-1] == {"message_thread_id": 777})
    q4 = FakePick("pick:hoops", thread_id=777)
    await bot.on_pick_callback(types.SimpleNamespace(callback_query=q4),
                               types.SimpleNamespace(bot=fake_bot))
    check("topic fallback link also carries the thread id",
          fake_bot.sent_messages[-1][2].get("message_thread_id") == 777)
    # Case: send_game must receive the short name exactly as registered in
    # BotFather (Telegram treats them as case-sensitive) even when the
    # incoming callback data arrives in a different case.
    q5 = FakePick("pick:LunaDefender")
    await bot.on_pick_callback(types.SimpleNamespace(callback_query=q5),
                               types.SimpleNamespace(bot=fake_bot))
    check("pick sends the registered case (LunaDefender)",
          fake_bot.sent_games[-1] == (-100123, "LunaDefender"))
    q6 = FakePick("pick:lunadefender")
    await bot.on_pick_callback(types.SimpleNamespace(callback_query=q6),
                               types.SimpleNamespace(bot=fake_bot))
    check("lowercase pick data still sends the registered case",
          fake_bot.sent_games[-1] == (-100123, "LunaDefender"))
    q7 = FakePick("pick:LUNABLOCKS")
    await bot.on_pick_callback(types.SimpleNamespace(callback_query=q7),
                               types.SimpleNamespace(bot=fake_bot))
    check("uppercase pick data still sends the registered case (LunaBlocks)",
          fake_bot.sent_games[-1] == (-100123, "LunaBlocks"))
    # LUNACLIMB is registered ALL CAPS in BotFather — the picker must send
    # exactly that, whatever case the callback data arrives in.
    q8 = FakePick("pick:lunaclimb")
    await bot.on_pick_callback(types.SimpleNamespace(callback_query=q8),
                               types.SimpleNamespace(bot=fake_bot))
    check("lowercase pick data still sends the registered case (LUNACLIMB)",
          fake_bot.sent_games[-1] == (-100123, "LUNACLIMB"))
    q9 = FakePick("pick:LUNACLIMB")
    await bot.on_pick_callback(types.SimpleNamespace(callback_query=q9),
                               types.SimpleNamespace(bot=fake_bot))
    check("exact-case pick sends LUNACLIMB",
          fake_bot.sent_games[-1] == (-100123, "LUNACLIMB"))


asyncio.run(pick_case())


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
    q3 = FakeCallback("Hoops")
    await bot.on_game_callback(types.SimpleNamespace(callback_query=q3), None)
    check("BotFather case difference still resolves", q3.answer_args == {"url": bot.HOOPS_URL})
    q4 = FakeCallback("LUNACLIMB")
    await bot.on_game_callback(types.SimpleNamespace(callback_query=q4), None)
    check("Play callback returns the Climb URL", q4.answer_args == {"url": bot.CLIMB_URL})


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
    check("empty inline query offers all twenty games", iq.answer_args[0] == ALL_SHORT_NAMES)
    iq2 = FakeInlineQuery("hoop")
    await bot.on_inline_query(types.SimpleNamespace(inline_query=iq2), None)
    check("inline search filters by name", iq2.answer_args[0] == ["hoops"])
    iq3 = FakeInlineQuery("blocks")
    await bot.on_inline_query(types.SimpleNamespace(inline_query=iq3), None)
    check("inline search finds Luna Blocks", iq3.answer_args[0] == ["LunaBlocks"])
    iq4 = FakeInlineQuery("penalty")
    await bot.on_inline_query(types.SimpleNamespace(inline_query=iq4), None)
    check("inline search finds Penalty Kick", iq4.answer_args[0] == ["Penalty"])


asyncio.run(inline_case())

print()
print("FAILURES:", fails if fails else "none")
sys.exit(1 if fails else 0)
