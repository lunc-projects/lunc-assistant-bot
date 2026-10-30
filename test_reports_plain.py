"""Regression tests for the 2026-10-29 report-send bug.

Root cause: /botstats and the 7 PM daily combined report were sent
with parse_mode=MARKDOWN. The text contains "(America/New_York)" —
its "_" opens a legacy-Markdown italic entity that never closes.
Telegram rejected the send: "BadRequest: Can't parse entities:
can't find end of the entity starting at byte offset 44". The
owner got only the error alert for /botstats, and job_usage_report
swallowed the same exception in its try/except, so the combined
report silently NEVER arrived.

Fix: report texts are plain data — headings no longer carry
Markdown asterisks, and both send sites pass NO parse_mode.

These tests prove: (1) the byte-offset-44 diagnosis on the original
text, (2) the exact current texts (solo + combined, realistic
content incl. underscores and % signs) are produced, and (3) both
send paths call Telegram with parse_mode=None.

Run: python3 test_reports_plain.py"""
import asyncio
import datetime as real_dt
import os
import sys
import tempfile
import types

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
_TMP = tempfile.mkdtemp()
os.environ["DB_PATH"] = os.path.join(_TMP, "test.db")
os.environ["OWNER_TELEGRAM_ID"] = "999"

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
ext.TypeHandler = _DummyHandler
ext.ContextTypes = types.SimpleNamespace(DEFAULT_TYPE=object)
ext.filters = types.SimpleNamespace()
tg.ext = ext

sys.modules["telegram"] = tg
sys.modules["telegram.constants"] = constants
sys.modules["telegram.error"] = error
sys.modules["telegram.ext"] = ext

import bot
import store

fails = []


def check(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        fails.append(name)


NS = types.SimpleNamespace

# ============ (1) The diagnosis, byte for byte ============
# The exact first line /botstats produced on 2026-10-29 before the
# fix (heading + day line from format_usage_report).
old_line = "📊 *Bot usage* — 2026-10-29 (America/New_York)"
check("root cause: byte offset 44 is the '_' of America/New_York",
      old_line.encode("utf-8")[44:45] == b"_")
check("root cause: that '_' has no closing partner on the line",
      old_line.count("_") == 1)

# ============ (2) Current texts: plain, complete, realistic ============
fixed = {
    "day": "2026-10-29", "groups_member": 12, "groups_unknown": 3, "groups_left": 1,
    "groups_active_today": 4, "new_groups_today": 1, "people_total": 231,
    "people_dm_total": 58, "people_group_total": 204, "people_active_today": 17,
    "dm_active_today": 3, "new_people_today": 2,
    "interactions_today": {"command": 61, "message": 74, "button": 7, "other": 0},
    "interactions_total": 142, "messages_logged": 3412,
    "wallet_watches": 2, "wallet_watch_users": 1,
}
legacy = {"groups": 9, "people_in_groups": 180, "dm_users": 40, "messages": 3412}

solo = bot.format_usage_report(fixed, legacy, 12340, 200000, heading="📊 Bot usage")
check("solo text keeps the day/timezone line verbatim",
      "(America/New_York)" in solo)
check("solo text has NO markdown asterisks anywhere", "*" not in solo)
check("solo text shows Wallet Security counts", "Wallet Security: 2 wallet(s) watched for 1 people" in solo)

_now = int(real_dt.datetime.now().timestamp())
_garuda = {"bot": "garuda", "ts": _now, "groups_logging": 3, "people_in_groups": 40,
           "dm_users": 6, "messages_logged": 900, "pot_spent": 100, "pot_budget": 200000}
_prof = {"bot": "professor", "ts": _now, "groups_serving": 4,
         "group_questions_today": 6, "dm_askers_today": 2}
_do = {"bot": "do", "ts": _now, "groups_logging": 2, "people_in_groups": 30,
       "dm_users": 5, "messages_logged": 700}
combined = bot.format_combined_report(fixed, legacy, 12340, 200000,
                                      {"garuda": _garuda, "professor": _prof,
                                       "do": _do}, now_ts=_now)
check("combined text has NO markdown asterisks anywhere", "*" not in combined)
check("combined keeps bot sections", "Garuda Assistant — as of" in combined
      and "Professor Crypto — as of" in combined and "DO Chain Assistant — as of" in combined)
check("combined keeps % -bearing content intact", "tokens" in combined)

# ============ (3a) /botstats sends PLAIN ============
replies = []


class _Msg:
    async def reply_text(self, text, parse_mode="<<unset>>", **kw):
        replies.append((text, parse_mode))


upd = NS(effective_user=NS(id=999), effective_message=_Msg(),
         effective_chat=NS(id=999, type="private"))
asyncio.run(bot.on_botstats(upd, NS(args=[])))
check("/botstats replied exactly once", len(replies) == 1)
check("/botstats sent with NO parse_mode (plain text)",
      replies and replies[0][1] == "<<unset>>")
check("/botstats text is the usage report", replies and "Bot usage" in replies[0][0])

# ============ (3b) the 7 PM job sends the combined report PLAIN ============
sent = []


class _FakeBot:
    id = 424242

    async def send_message(self, chat_id, text, parse_mode=None):
        sent.append((chat_id, text, parse_mode))


class _FakeDateTime(real_dt.datetime):
    @classmethod
    def now(cls, tz=None):
        return real_dt.datetime(2026, 10, 29, 20, 0, tzinfo=tz)


async def _fake_read_ok(name):
    return {"garuda": _garuda, "professor": _prof, "do": _do}[name]


_sr = bot.stats_report
_real_read_bot = _sr.read_bot
_real_bot_dt = bot.datetime
_real_et_day = store.et_day
os.environ["UPSTASH_STATS_URL"] = "https://stats.example.test"
os.environ["UPSTASH_STATS_TOKEN"] = "tok123"
bot.datetime = types.SimpleNamespace(datetime=_FakeDateTime, timezone=real_dt.timezone,
                                     timedelta=real_dt.timedelta)
store.et_day = lambda ts=None: "2026-10-29"
bot.OWNER_ID = 999
try:
    _sr.read_bot = _fake_read_ok
    store.set_setting(0, "usage_report_day", "")
    asyncio.run(bot.job_usage_report(NS(bot=_FakeBot())))
finally:
    _sr.read_bot = _real_read_bot
    bot.datetime = _real_bot_dt
    store.et_day = _real_et_day
    os.environ.pop("UPSTASH_STATS_URL", None)
    os.environ.pop("UPSTASH_STATS_TOKEN", None)

check("combined job sent exactly once", len(sent) == 1)
check("combined job sent to the owner", sent and sent[0][0] == 999)
check("combined job sent with parse_mode=None (plain text)",
      sent and sent[0][2] is None)
check("combined job text is the all-bots report",
      sent and "Daily usage — all bots" in sent[0][1])
check("combined job marked the day sent (send succeeded in-job)",
      store.get_setting(0, "usage_report_day") == "2026-10-29")

print()
if fails:
    print("FAILURES:", len(fails))
    sys.exit(1)
print("ALL PASS")
