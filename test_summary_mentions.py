# Summary no-mentions + brevity tests (owner decisions 2026-10-28):
# summaries must be SHORT and must never carry a live @mention, because
# Telegram re-tags (pings) anyone written as @name in a summary.
# Run: python3 test_summary_mentions.py
import asyncio
import inspect
import os
import sys
import tempfile
import types

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["OWNER_TELEGRAM_ID"] = "999"

# --- Dependency stubs (same pattern as test_ai_policy.py / test_filter.py) ---
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


sm = ai_client.strip_mentions

print("== strip_mentions: handles lose the @ ==")
check(sm("@steve_b opened the topic") == "steve_b opened the topic",
      "handle at start of string")
check(sm("• @anna_k raised the vote") == "• anna_k raised the vote",
      "handle at start of a line/bullet")
check(sm("ask @anna_k about the vote") == "ask anna_k about the vote",
      "handle mid-sentence")
check(sm("@steve_b and @anna_k agreed, cc @carl_99") == "steve_b and anna_k agreed, cc carl_99",
      "multiple handles in one text")
check(sm("(@carl_99) confirmed it") == "(carl_99) confirmed it",
      "handle in parentheses")
check(sm('"@dora_x" was quoted') == '"dora_x" was quoted',
      "handle after a quote mark")
check(sm("thanks @Luncassistantbot!") == "thanks Luncassistantbot!",
      "handle followed by punctuation")

print("== strip_mentions: non-mentions untouched ==")
check(sm("mail bob.smith@example.com today") == "mail bob.smith@example.com today",
      "email address untouched")
check(sm("user@host_name is not a mention") == "user@host_name is not a mention",
      "@ glued to a word stays")
check(sm("meet @ab later") == "meet @ab later",
      "under 3 handle chars stays (not a valid handle)")
check(sm("no handles here") == "no handles here", "plain text unchanged")
check(sm("") == "", "empty string safe")

print("== send path: ai_client.summarize sanitizes AI output ==")
rows = [{"ts": 1, "user_name": "Steve", "text": "hello @anna_k check the vote"}]


async def fake_chat(messages, temperature=0.3, lang="en"):
    return "⚡ TL;DR — vote talk\n• @steve_b proposed it, @anna_k seconded"


real_chat = ai_client.chat
ai_client.chat = fake_chat
try:
    out = asyncio.run(ai_client.summarize(rows))
finally:
    ai_client.chat = real_chat
check("@steve_b" not in out and "@anna_k" not in out, "AI summary ships with no @handles")
check("steve_b proposed it" in out, "bare names survive in the AI summary")

print("== send path: extractive fallback sanitizes too ==")
out = ai_client.extractive_summary(rows)
check("@anna_k" not in out and "anna_k" in out,
      "extractive summary strips handles quoted from the log")

print("== send path: /tldr wired through the sanitizer ==")
check("strip_mentions" in inspect.getsource(bot.on_tldr),
      "bot.on_tldr passes its output through strip_mentions")
check("never write @usernames" in inspect.getsource(bot.on_tldr),
      "bot.on_tldr prompt forbids @usernames")

print("== brevity instruction ==")
check("at most 5 short lines" in ai_client.SUMMARY_SYSTEM
      and "about 450 characters" in ai_client.SUMMARY_SYSTEM,
      "SUMMARY_SYSTEM caps length (~5 lines / ~450 chars)")
check("NEVER write @usernames" in ai_client.SUMMARY_SYSTEM,
      "SUMMARY_SYSTEM forbids @usernames")
check("@name if named" not in ai_client.SUMMARY_SYSTEM,
      "old action-items @name instruction is gone")

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
