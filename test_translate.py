"""Auto-translate tests (2026-11-11): content guards, engine-response
decisions with a mocked getter, cooldown/cap/cache gates, the per-chat
store toggle, and bot-level wiring (toggle off = silent, PM explains,
non-admin cannot flip the switch).

v2 (same day): the AI second engine — output parsing (English
sentinel, refusal), engine order (Google primary; AI on Google
failure/echo; AI never for long messages), use_ai=False == v1, and
the translation token sub-budget (accounting, full refund on
failure, AI stops when spent, UTC-midnight reset).

No network: both engine getters are injected everywhere.
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


async def no_ai(text):
    """AI engine that never answers — pins the Google path in tests,
    whatever the environment (tests must never spend real AI calls)."""
    return None


ai_calls = []


def make_ai(response=None, exc=None):
    async def ai_getter(text):
        ai_calls.append(text)
        if exc:
            raise exc
        return response
    return ai_getter


TURK = "Klavye ayarlarını değiştirebilirsin"

del calls[:]
t = tr.Translator(ai_getter=no_ai, getter=make_getter(GTX_TR))
out = run(t.translate(TURK, chat_id=-1, user_id=7, now=1000))
check(out == "You can change keyboard settings", "Turkish message gets its translation")
check(len(calls) == 1, "getter called once")

# English detected by the engine -> silent
GTX_EN = [[["The vote ends tomorrow", "The vote ends tomorrow", None, None, 5]], None, "en"]
t = tr.Translator(ai_getter=no_ai, getter=make_getter(GTX_EN))
check(run(t.translate("The vote ends tomorrow morning", -1, 7, now=1000)) is None,
      "English (detected en) skipped")

# Echo result -> silent
GTX_ECHO = [[["Gracias a todos por venir", "Gracias a todos por venir", None, None, 1]], None, "es"]
t = tr.Translator(ai_getter=no_ai, getter=make_getter(GTX_ECHO))
check(run(t.translate("Gracias a todos por venir", -1, 7, now=1000)) is None,
      "echo translation skipped")

# Engine failure -> silent, no exception
t = tr.Translator(ai_getter=no_ai, getter=make_getter(exc=RuntimeError("boom")))
check(run(t.translate(TURK, -1, 7, now=1000)) is None, "engine exception is silent")
t = tr.Translator(ai_getter=no_ai, getter=make_getter(None))
check(run(t.translate(TURK, -1, 7, now=1000)) is None, "engine None is silent")

# Guards short-circuit before any HTTP
del calls[:]
t = tr.Translator(ai_getter=no_ai, getter=make_getter(GTX_TR))
check(run(t.translate("/help me please now", -1, 7, now=1000)) is None and not calls,
      "guarded messages never reach the engine")

# ---------- cooldown / cap / cache ----------
t = tr.Translator(ai_getter=no_ai, getter=make_getter(GTX_TR))
run(t.translate(TURK, -1, 7, now=1000))
check(run(t.translate("Başka bir cümle kuruyorum şimdi", -1, 7, now=1010)) is None,
      "same user inside 30s cooldown is skipped")
check(run(t.translate("Başka bir cümle kuruyorum şimdi", -1, 7, now=1031)) is not None,
      "same user after cooldown is translated")

t = tr.Translator(ai_getter=no_ai, getter=make_getter(GTX_TR), hourly_cap=3)
outs = [run(t.translate(f"Cümle numara {i} burada geçiyor", -5, 100 + i, now=2000 + i * 40))
        for i in range(4)]
check(outs[:3] != [None] * 3 and outs[3] is None, "chat hourly cap stops the 4th translation")
check(run(t.translate("Cümle başka sohbete gidiyor", -6, 100, now=2100)) is not None,
      "cap is per chat, other chat unaffected")
check(run(t.translate("Cümle numara dokuz burada", -5, 200, now=2000 + 3601)) is not None,
      "cap window slides after an hour")

del calls[:]
t = tr.Translator(ai_getter=no_ai, getter=make_getter(GTX_TR))
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

bot.TRANSLATOR = tr.Translator(ai_getter=no_ai, getter=make_getter(GTX_TR))


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

# ---------- v2: AI output parsing ----------
check(tr.parse_ai_output("[[ENGLISH]]") == ("english", None), "AI sentinel means English")
check(tr.parse_ai_output("  [[ENGLISH]].") == ("english", None),
      "sentinel with trailing dot still English")
check(tr.parse_ai_output("Merhaba dünya") == ("ok", "Merhaba dünya"),
      "AI translation passes through")
check(tr.parse_ai_output("") is None and tr.parse_ai_output(None) is None
      and tr.parse_ai_output("   ") is None, "empty AI reply is a failure")
check(tr.parse_ai_output("I'm sorry, I can't translate that.") is None,
      "AI refusal is a failure, not a translation")

# ---------- v2: engine order — Google primary, AI fallback ----------
# (The AI is the fallback until the live Groq-vs-gtx quality proof is
# run — see translate.py's header. These tests pin the order.)
AI_TR = "You can change your keyboard settings"
GTX_FAIL = make_getter(exc=RuntimeError("gtx down"))

del calls[:]; del ai_calls[:]
t = tr.Translator(getter=make_getter(GTX_TR), ai_getter=make_ai(AI_TR))
out = run(t.translate(TURK, -1, 7, now=1000))
check(out == "You can change keyboard settings" and not ai_calls,
      "Google success -> Google translation, AI untouched")

del calls[:]; del ai_calls[:]
t = tr.Translator(getter=GTX_FAIL, ai_getter=make_ai(AI_TR))
out = run(t.translate(TURK, -1, 7, now=1000))
check(out == AI_TR and len(ai_calls) == 1,
      "Google failure -> AI translation used")

t = tr.Translator(getter=make_getter(None), ai_getter=make_ai(AI_TR))
check(run(t.translate(TURK, -1, 7, now=1000)) == AI_TR,
      "Google empty reply -> AI translation used")

del ai_calls[:]
t = tr.Translator(getter=make_getter(GTX_ECHO), ai_getter=make_ai(AI_TR))
out = run(t.translate("Gracias a todos por venir", -1, 7, now=1000))
check(out == AI_TR and len(ai_calls) == 1,
      "Google echo (misdetection) -> AI gets its chance")

del ai_calls[:]
t = tr.Translator(getter=make_getter(GTX_EN), ai_getter=make_ai(AI_TR))
check(run(t.translate("The vote ends tomorrow morning", -1, 7, now=1000)) is None
      and not ai_calls,
      "Google-detected English stays silent, AI untouched")

t = tr.Translator(getter=GTX_FAIL, ai_getter=make_ai("[[ENGLISH]]"))
check(run(t.translate("The vote ends tomorrow morning", -1, 7, now=1000)) is None,
      "AI English sentinel (after Google failure) stays silent")

for label, ai in [("exception", make_ai(exc=RuntimeError("boom"))),
                  ("None", make_ai(None)),
                  ("refusal", make_ai("I'm sorry, I can't help with that.")),
                  ("echo", make_ai(TURK))]:
    t = tr.Translator(getter=GTX_FAIL, ai_getter=ai)
    check(run(t.translate(TURK, -1, 7, now=1000)) is None,
          f"Google down + AI {label} -> silent (exactly v1's failure mode)")

del ai_calls[:]
long_text = " ".join(["kelime"] * 130)  # ~900 chars, passes the guards
t = tr.Translator(getter=GTX_FAIL, ai_getter=make_ai(AI_TR))
check(run(t.translate(long_text, -1, 7, now=1000)) is None and not ai_calls,
      "long message never tried on the AI (250-token output cap)")

del ai_calls[:]
t = tr.Translator(getter=GTX_FAIL, ai_getter=make_ai(AI_TR), use_ai=False)
check(run(t.translate(TURK, -1, 7, now=1000)) is None and not ai_calls
      and t.ai_spent(1000) == 0,
      "use_ai=False is exactly v1 (no AI, no budget movement)")

# ---------- v2: translation sub-budget accounting ----------
t = tr.Translator(getter=GTX_FAIL, ai_getter=make_ai(AI_TR))
run(t.translate(TURK, -1, 7, now=1000))
exp_in = (len(tr.TRANSLATE_SYSTEM) + tr.AI_RULES_CHARS + len(TURK)) // 4
exp_out = min(tr.AI_MAX_OUTPUT_TOKENS, len(AI_TR) // 4 + 1)
check(t.ai_spent(1000) == exp_in + exp_out,
      f"budget accounting: spent == input est + actual output ({exp_in}+{exp_out})")

t = tr.Translator(getter=GTX_FAIL, ai_getter=make_ai(exc=RuntimeError("boom")))
run(t.translate(TURK, -1, 7, now=1000))
check(t.ai_spent(1000) == 0, "failed AI call refunds the budget in full")

del ai_calls[:]
t = tr.Translator(getter=GTX_FAIL, ai_getter=make_ai(AI_TR),
                  ai_daily_cap=tr.Translator._ai_estimate(TURK))
run(t.translate(TURK, -1, 7, now=1000))
check(len(ai_calls) == 1, "first AI fallback used within budget")
check(run(t.translate("Başka bir cümle kuruyorum şimdi", -1, 8, now=2000)) is None
      and len(ai_calls) == 1,
      "sub-budget spent -> AI no longer tried (Google primary unaffected)")
run(t.translate("Yarın yine gelirim buraya", -1, 9, now=1000 + 90000))
check(len(ai_calls) == 2, "sub-budget resets at UTC midnight")

del ai_calls[:]
t = tr.Translator(getter=GTX_FAIL, ai_getter=make_ai(AI_TR))
run(t.translate(TURK, -1, 7, now=1000))
out = run(t.translate(TURK, -1, 8, now=2000))
check(out == AI_TR and len(ai_calls) == 1,
      "AI translation served from cache on repeat")

# ---------- v2: bot-level wiring with the AI engine ----------
bot.TRANSLATOR = tr.Translator(getter=GTX_FAIL,
                               ai_getter=make_ai(AI_TR), use_ai=True)
store.set_translate_enabled(-100, True)
upd = fake_update(TURK)
run(bot.maybe_translate(upd, CTX))
check(upd.message.replies == [AI_TR],
      "bot falls back to the AI translation when Google is down")

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
