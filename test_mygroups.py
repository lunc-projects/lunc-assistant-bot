"""Tests for the owner-only /mygroups command (added 2026-11-25).

The daily usage report counts the groups the bot belongs to from
usage_chats (ids only — no names are stored, by privacy design).
/mygroups resolves those ids to names at ask-time via get_chat and
sends the owner a plain-text list.

Proves: (1) the reply lists exactly the confirmed-member groups
(usage_chats is_member = 1, negative ids) with resolved titles,
@username when public, and a plain fallback line when a lookup
fails; (2) non-members / removed groups / DM chats never appear;
(3) the send is PLAIN (no parse_mode) so user-controlled titles
cannot break it; (4) a non-owner gets "Owner only." and no lookup
is ever made.

Run: python3 test_mygroups.py"""
import asyncio
import os
import sqlite3
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

# ============ Seed the usage registry ============
store._conn()  # create schema on the empty DB
c = sqlite3.connect(store.DB)
# three confirmed member groups
c.execute("INSERT INTO usage_chats(chat_id, chat_type, first_seen_ts, last_seen_ts, is_member, seeded)"
          " VALUES(-1001, 'supergroup', 1700000000, 1700000100, 1, 0)")
c.execute("INSERT INTO usage_chats(chat_id, chat_type, first_seen_ts, last_seen_ts, is_member, seeded)"
          " VALUES(-1002, 'supergroup', 1700000000, 1700000100, 1, 0)")
c.execute("INSERT INTO usage_chats(chat_id, chat_type, first_seen_ts, last_seen_ts, is_member, seeded)"
          " VALUES(-1003, 'group', 1700000000, 1700000100, 1, 0)")
# a group that removed the bot, and a DM chat wrongly flagged member:
# neither may ever be listed
c.execute("INSERT INTO usage_chats(chat_id, chat_type, first_seen_ts, last_seen_ts, is_member, seeded)"
          " VALUES(-1004, 'supergroup', 1700000000, 1700000100, 0, 0)")
c.execute("INSERT INTO usage_chats(chat_id, chat_type, first_seen_ts, last_seen_ts, is_member, seeded)"
          " VALUES(555, 'private', 1700000000, 1700000100, 1, 0)")
c.commit(); c.close()

check("store helper returns exactly the confirmed member groups",
      store.member_group_chat_ids() == [-1003, -1002, -1001])

# ============ Fake Telegram side ============
lookups = []


class _FakeBot:
    id = 424242

    async def get_chat(self, chat_id):
        lookups.append(chat_id)
        if chat_id == -1001:
            return NS(title="LUNC Traders *Main*", username="lunctrader")
        if chat_id == -1002:
            return NS(title="Quiet Corner", username=None)
        raise Exception("Chat not found")


replies = []


class _Msg:
    async def reply_text(self, text, parse_mode="<<unset>>", **kw):
        replies.append((text, parse_mode))


# ============ (1) Owner gets the resolved plain list ============
upd = NS(effective_user=NS(id=999), effective_message=_Msg(),
         effective_chat=NS(id=999, type="private"))
asyncio.run(bot.on_mygroups(upd, NS(bot=_FakeBot(), args=[])))
check("owner: replied exactly once", len(replies) == 1)
text = replies[0][0] if replies else ""
check("owner: sent PLAIN (no parse_mode)", replies and replies[0][1] == "<<unset>>")
check("owner: heading counts 3 groups", "Groups I'm in (3):" in text)
check("owner: title + @username resolved",
      "LUNC Traders *Main* (@lunctrader) — -1001" in text)
check("owner: title without username has no @",
      "Quiet Corner — -1002" in text)
check("owner: failed lookup falls back to id + note",
      "-1003 — (couldn't look up — maybe removed)" in text)
check("owner: removed group never listed", "-1004" not in text)
check("owner: DM chat never listed", "555" not in text)
check("owner: lookups made only for member groups",
      sorted(lookups) == [-1003, -1002, -1001])

# ============ (2) Non-owner gets nothing ============
replies.clear()
lookups.clear()
upd2 = NS(effective_user=NS(id=123), effective_message=_Msg(),
          effective_chat=NS(id=123, type="private"))
asyncio.run(bot.on_mygroups(upd2, NS(bot=_FakeBot(), args=[])))
check("non-owner: only the refusal is sent",
      len(replies) == 1 and replies[0][0] == "Owner only.")
check("non-owner: no chat lookups made", lookups == [])

print()
if fails:
    print("FAILURES:", len(fails))
    sys.exit(1)
print("ALL PASS")
