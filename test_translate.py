"""Auto-translate tests (2026-11-11): content guards, engine-response
decisions with a mocked getter, cooldown/cap/cache gates, the per-chat
store toggle, and bot-level wiring (toggle off = silent, PM explains,
non-admin cannot flip the switch).

No network: the translation getter is injected everywhere.
Run: python3 test_translate.py"""
import asyncio
import os
import sys
import tempfile
import types

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["OWNER_TELEGRAM_ID"] = "999"

# --- Dependency stubs (same pattern as test_ai_policy.py) ---
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

import store
import translate as tr

passed = 0
failed = 0


def check(cond, msg):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ok: {msg}")
    else:
        failed += 1
        print(f"  FAIL: {msg}")


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------- content guards (pure) ----------
check(tr.skip_reason("/price lütfen şimdi bak") == "command", "command skipped")
check(tr.skip_reason("Selam") == "too short", "one short word skipped")
check(tr.skip_reason("Merhaba nasılsın") == "too few words", "two words skipped")
check(tr.skip_reason("bak https://example.com/abcdef şimdi") is not None,
      "link-heavy message skipped")
check(tr.skip_reason("terra1qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq9yf8pz bak bak") is not None,
      "address-heavy message skipped")
check(tr.skip_reason("1234567890 🔥🔥🔥🔥🔥 987654321") is not None,
      "numbers/emoji message skipped")
check(tr.skip_reason("Klavye ayarlarını değiştirebilirsin") is None,
      "real Turkish sentence passes the guards")
check(tr.skip_reason("La votación del validador termina mañana") is None,
      "real Spanish sentence passes the guards")

# ---------- gtx response parsing ----------
GTX_TR = [[["You can change keyboard settings", "Klavye ayarlarını değiştirebilirsin",
             None, None, 3]], None, "tr"]
check(tr.parse_gtx(GTX_TR) == ("You can change keyboard settings", "tr"),
      "gtx response parsed (text + detected lang)")
multi = [[["Hola ", "Merhaba ", None, None, 1], ["mundo", "dünya", None, None, 1]], None, "tr"]
check(tr.parse_gtx(multi)[0] == "Hola mundo", "multi-segment response joined")
check(tr.parse_gtx(None) is None and tr.parse_gtx([]) is None and tr.parse_gtx([[]]) is None,
      "garbage responses parse to None")

# ---------- Translator decisions with a mocked getter ----------
calls = []


def make_getter(response=None, exc=None):
    async def getter(text):
        calls.append(text)
        if exc:
            raise exc
        return response
    return getter


TURK = "Klavye ayarlarını değiştirebilirsin"

del calls[:]
t = tr.Translator(getter=make_getter(GTX_TR))
out = run(t.translate(TURK, chat_id=-1, user_id=7, now=1000))
check(out == "You can change keyboard settings", "Turkish message gets its translation")
check(len(calls) == 1, "getter called once")

# English detected by the engine -> silent
GTX_EN = [[["The vote ends tomorrow", "The vote ends tomorrow", None, None, 5]], None, "en"]
t = tr.Translator(getter=make_getter(GTX_EN))
check(run(t.translate("The vote ends tomorrow morning", -1, 7, now=1000)) is None,
      "English (detected en) skipped")

# Echo result -> silent
GTX_ECHO = [[["Gracias a todos por venir", "Gracias a todos por venir", None, None, 1]], None, "es"]
t = tr.Translator(getter=make_getter(GTX_ECHO))
check(run(t.translate("Gracias a todos por venir", -1, 7, now=1000)) is None,
      "echo translation skipped")

# Engine failure -> silent, no exception
t = tr.Translator(getter=make_getter(exc=RuntimeError("boom")))
check(run(t.translate(TURK, -1, 7, now=1000)) is None, "engine exception is silent")
t = tr.Translator(getter=make_getter(None))
check(run(t.translate(TURK, -1, 7, now=1000)) is None, "engine None is silent")

# Guards short-circuit before any HTTP
del calls[:]
t = tr.Translator(getter=make_getter(GTX_TR))
check(run(t.translate("/help me please now", -1, 7, now=1000)) is None and not calls,
      "guarded messages never reach the engine")

# ---------- cooldown / cap / cache ----------
t = tr.Translator(getter=make_getter(GTX_TR))
run(t.translate(TURK, -1, 7, now=1000))
check(run(t.translate("Başka bir cümle kuruyorum şimdi", -1, 7, now=1010)) is None,
      "same user inside 30s cooldown is skipped")
check(run(t.translate("Başka bir cümle kuruyorum şimdi", -1, 7, now=1031)) is not None,
      "same user after cooldown is translated")

t = tr.Translator(getter=make_getter(GTX_TR), hourly_cap=3)
outs = [run(t.translate(f"Cümle numara {i} burada geçiyor", -5, 100 + i, now=2000 + i * 40))
        for i in range(4)]
check(outs[:3] != [None] * 3 and outs[3] is None, "chat hourly cap stops the 4th translation")
check(run(t.translate("Cümle başka sohbete gidiyor", -6, 100, now=2100)) is not None,
      "cap is per chat, other chat unaffected")
check(run(t.translate("Cümle numara dokuz burada", -5, 200, now=2000 + 3601)) is not None,
      "cap window slides after an hour")

del calls[:]
t = tr.Translator(getter=make_getter(GTX_TR))
run(t.translate(TURK, -1, 7, now=1000))
out = run(t.translate(TURK, -1, 8, now=2000))  # different user, later
check(out == "You can change keyboard settings" and len(calls) == 1,
      "repeated string served from cache (no second engine call)")

# ---------- store toggle ----------
check(store.translate_enabled(-100) is True, "unset group defaults to translate ON")
store.set_translate_enabled(-100, False)
check(store.translate_enabled(-100) is False, "toggled off reads off")
check(store.translate_enabled(-200) is True, "another group unaffected")
store.set_translate_enabled(-100, True)
check(store.translate_enabled(-100) is True, "toggled back on reads on")

# ---------- bot-level wiring ----------
import bot

bot.TRANSLATOR = tr.Translator(getter=make_getter(GTX_TR))


class FakeMsg:
    def __init__(self, text):
        self.text = text
        self.sender_chat = None
        self.replies = []

    async def reply_text(self, text, **kw):
        self.replies.append(text)


def fake_update(text, chat_id=-100, chat_type="supergroup", user_id=7, is_bot=False):
    msg = FakeMsg(text)
    upd = types.SimpleNamespace(
        message=msg,
        effective_message=msg,
        effective_user=types.SimpleNamespace(id=user_id, is_bot=is_bot),
        effective_chat=types.SimpleNamespace(id=chat_id, type=chat_type),
    )
    return upd


CTX = types.SimpleNamespace(bot=None, args=[])

store.set_translate_enabled(-100, True)
upd = fake_update(TURK)
run(bot.maybe_translate(upd, CTX))
check(upd.message.replies == ["You can change keyboard settings"],
      "bot replies with the translation in an enabled group")

store.set_translate_enabled(-100, False)
upd = fake_update(TURK)
run(bot.maybe_translate(upd, CTX))
check(upd.message.replies == [], "toggle OFF group stays silent")

store.set_translate_enabled(-100, True)
upd = fake_update(TURK, is_bot=True)
run(bot.maybe_translate(upd, CTX))
check(upd.message.replies == [], "bot senders are never translated")

upd = fake_update(TURK, chat_id=-300, chat_type="private")
run(bot.maybe_translate(upd, CTX))
check(upd.message.replies == [], "private chats are never auto-translated")


class FakeBot:
    def __init__(self, status):
        self.status = status

    async def get_chat_member(self, chat_id, user_id):
        return types.SimpleNamespace(status=self.status)


# /translate in PM explains the group feature
upd = fake_update("/translate", chat_id=42, chat_type="private")
run(bot.on_translate(upd, types.SimpleNamespace(bot=FakeBot("member"), args=[])))
check(upd.message.replies and "group feature" in upd.message.replies[0],
      "/translate in PM explains it is a group feature")

# non-admin cannot switch it off
store.set_translate_enabled(-100, True)
upd = fake_update("/translate", chat_id=-100)
run(bot.on_translate(upd, types.SimpleNamespace(bot=FakeBot("member"), args=["off"])))
check(store.translate_enabled(-100) is True and "Only group admins" in upd.message.replies[0],
      "non-admin cannot toggle translate off")

# admin can switch it off and on
upd = fake_update("/translate", chat_id=-100)
run(bot.on_translate(upd, types.SimpleNamespace(bot=FakeBot("administrator"), args=["off"])))
check(store.translate_enabled(-100) is False, "admin toggles translate off")
upd = fake_update("/translate", chat_id=-100)
run(bot.on_translate(upd, types.SimpleNamespace(bot=FakeBot("administrator"), args=["on"])))
check(store.translate_enabled(-100) is True, "admin toggles translate back on")

check("/translate on/off" in bot.HELP, "help carries the translate line")

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
