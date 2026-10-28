"""AI policy tests (owner decisions 2026-10-27): every AI answer is
capped at 250 output tokens, answers are short + plain-text-only (no
image/video links or media), and hard content rules — refuse
pornographic/erotic content and hacking/illicit how-to, with a short
polite refusal — ride along on EVERY AI call via ai_client.with_rules,
while defensive security education stays allowed. Also pins the
user-facing cap strings to the flat 1-question-per-day rule.

Run: python3 test_ai_policy.py"""
import inspect
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

import ai_client
import bot

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


print("== smaller answers ==")
check(ai_client.MAX_TOKENS == 250, "MAX_TOKENS is 250 (was 500)")
check("well under 250 tokens" in ai_client.SUMMARY_SYSTEM,
      "summary prompt targets the 250-token budget")

print("== rules ride on every AI call ==")
check("with_rules" in inspect.getsource(ai_client.chat),
      "chat() applies with_rules to every call")
msgs = [{"role": "system", "content": "You are a bot."},
        {"role": "user", "content": "hi"}]
out = ai_client.with_rules(msgs)
sys_content = out[0]["content"]
check(out[0]["role"] == "system" and sys_content.startswith("You are a bot."),
      "rules are appended to the existing system message")
check(msgs[0]["content"] == "You are a bot.", "with_rules does not mutate its input")

print("== conciseness + text-only ==")
check("Keep it short and plain" in sys_content, "conciseness instruction present")
check("plain text only" in sys_content, "plain-text-only instruction present")
check("Do not include image or video links or media of any kind" in sys_content,
      "no-images/no-videos instruction present")

print("== hard content rules ==")
check("pornographic or erotic" in sys_content, "porn/erotic refusal rule present")
check("hacking instructions" in sys_content, "hacking refusal rule present")
for word in ("exploits", "malware", "phishing", "seed phrases", "access controls"):
    check(word in sys_content, f"hacking rule names {word!r}")
check("other illegal activity" in sys_content, "illicit how-to refusal rule present")
check(sys_content.count("short, polite refusal") >= 2, "refusals are short and polite")
check("protect themselves stays allowed" in sys_content,
      "defensive security education carve-out present")
check("spot scams and phishing" in sys_content, "scam-spotting education explicitly allowed")

print("== rules without a system message ==")
out2 = ai_client.with_rules([{"role": "user", "content": "hi"}])
check(out2[0]["role"] == "system" and "plain text only" in out2[0]["content"],
      "a system message is created when the call has none")

print("== flat-cap strings (1/day), old ladder gone ==")
check("1 per day for everyone" in bot.HELP, "help states the flat 1/day rule")
check("2 AI queries/day" not in bot.HELP and "6 AI queries/day" not in bot.HELP,
      "help no longer states the 2/4/6 ladder")
check("2 (starting), 4, or 6" not in bot.PRIVACY_TEXT,
      "privacy text no longer states the 2/4/6 ladder")
check("1 AI question a day" in bot.PRIVACY_TEXT, "privacy text states the flat rule")
guard_src = inspect.getsource(bot.ai_guard)
check("one AI question per day for everyone" in guard_src,
      "the limit message states the flat rule")
check("Ranks allow 2, 4, or 6" not in guard_src, "the limit message drops the ladder")
check("overridden" in guard_src, "the gate still honours owner-set rank overrides")

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
