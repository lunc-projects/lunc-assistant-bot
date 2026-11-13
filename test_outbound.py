"""Outbound anti-spam guard tests (2026-11-13): the bot must never
post a message that is ONLY links / @mentions again (it posted three
gibberish bot links in a group — see outbound.py).

Covers: the exact incident message is blocked; labelled alerts and
report forwards carrying links pass; sentences with a link or a
mention pass; sanitize strips bare link lines from AI text and
returns "" when nothing substantive remains; the Bot.send_message
choke point installed by bot._install_outbound_guard blocks group
sends, passes DM sends, and works for positional and keyword calls.

Run: python3 test_outbound.py"""
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


class _FakeBot:
    """Stand-in for telegram.Bot: records every send_message call."""
    calls = []

    async def send_message(self, chat_id=None, text=None, **kwargs):
        _FakeBot.calls.append((chat_id, text))
        return "SENT"


tg.Update = object
tg.InlineKeyboardButton = _Button
tg.InlineKeyboardMarkup = _Markup
tg.ChatPermissions = _Perms
tg.WebAppInfo = _WebApp
tg.InlineQueryResultGame = _GameResult
tg.Bot = _FakeBot

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

import outbound
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
        print(f"FAIL: {msg}")


INCIDENT = "@gAm0kiGk8bot\n@gbrcm9dfdbot\n@GIU3YH3Lbot"

# --- outbound_blocked: the spam shapes ---
check(outbound.outbound_blocked(INCIDENT), "incident message (3 bot links, one per line) blocked")
check(outbound.outbound_blocked("@gAm0kiGk8bot @gbrcm9dfdbot @GIU3YH3Lbot"), "3 bot links on one line blocked")
check(outbound.outbound_blocked("@somebot"), "single bare mention blocked")
check(outbound.outbound_blocked("https://t.me/whatevergroup"), "single bare t.me link blocked")
check(outbound.outbound_blocked("t.me/whatevergroup"), "bare t.me link without scheme blocked")
check(outbound.outbound_blocked("• @a1bot • @b2bot"), "bulleted mention list blocked")
check(outbound.outbound_blocked("[join](https://t.me/whatevergroup)"), "single markdown link blocked")

# --- outbound_blocked: legitimate sends pass ---
ALERT = ("🛡️ Wallet Security — change detected\n"
         "Wallet: terra1kur3cr4vask4lgs3tr4gww7lr0zvc944gjfcqc\n"
         "https://finder.terraclassic.community/mainnet/address/terra1kur3cr4vask4lgs3tr4gww7lr0zvc944gjfcqc\n"
         "https://finder.terraclassic.community/mainnet/tx/A69CB9537C8F04553")
check(not outbound.outbound_blocked(ALERT), "wallet security alert with finder links passes")

REPORT = ("🚩 Report in Garuda Universe Official Group\n"
          "Reported by: Yannis (1677379136)\n"
          "Message by: (5946803716)\n"
          "https://t.me/Garudaverse99/39169")
check(not outbound.outbound_blocked(REPORT), "report forward with t.me jump link passes")
check(not outbound.outbound_blocked("Ask @LuncAssistantBot about LUNC staking rewards"), "sentence with one @mention passes")
check(not outbound.outbound_blocked("Full guide: https://luncscan.com — worth a read"), "sentence with one link passes")
check(not outbound.outbound_blocked("LUNC price: $0.00012 📈"), "plain price line passes")
check(not outbound.outbound_blocked(""), "empty text not blocked")
check(not outbound.outbound_blocked("   "), "whitespace-only text not blocked")
check(not outbound.outbound_blocked(None), "None text not blocked")
check(not outbound.outbound_blocked("🔗🔗🔗"), "emoji-only text not blocked (no link token)")

# --- sanitize_ai_text ---
MIXED = ("The group mostly talked about staking rewards.\n"
         "@gAm0kiGk8bot\n@gbrcm9dfdbot\n"
         "Burns came up again near the end.")
clean = outbound.sanitize_ai_text(MIXED)
check("staking rewards" in clean and "Burns came up" in clean, "sanitize keeps the real summary lines")
check("@gAm0kiGk8bot" not in clean and "@gbrcm9dfdbot" not in clean, "sanitize strips the bare bot-mention line")
check(outbound.sanitize_ai_text(INCIDENT) == "", "sanitize of the incident text returns empty")
check(outbound.sanitize_ai_text("") == "", "sanitize of empty returns empty")
SENT = "Here is the explorer: https://luncscan.com — check the top validators page."
check(outbound.sanitize_ai_text(SENT) == SENT, "sanitize leaves a normal sentence untouched")

# --- is_group_chat_id ---
check(outbound.is_group_chat_id(-1001234567890), "supergroup id is a group chat id")
check(not outbound.is_group_chat_id(999), "owner DM id is not a group chat id")
check(not outbound.is_group_chat_id("@somechannel"), "string chat id not treated as group")

# --- The choke point: bot._install_outbound_guard on the Bot class ---
bot._install_outbound_guard()
bot._install_outbound_guard()  # installing twice must not double-wrap


async def choke():
    fb = _FakeBot()
    _FakeBot.calls = []
    r = await fb.send_message(-1001234567890, INCIDENT)
    check(r is None and _FakeBot.calls == [], "guard: group send of incident text blocked, orig never called")
    r = await fb.send_message(chat_id=-1001234567890, text=INCIDENT)
    check(r is None and _FakeBot.calls == [], "guard: keyword-style group send also blocked")
    r = await fb.send_message(-1001234567890, ALERT)
    check(r == "SENT" and len(_FakeBot.calls) == 1, "guard: group security alert passes through")
    r = await fb.send_message(999, INCIDENT)
    check(r == "SENT" and len(_FakeBot.calls) == 2, "guard: DM send is NOT blocked (owner forwards/alerts)")


asyncio.run(choke())

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
