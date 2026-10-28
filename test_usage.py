"""Usage registry tests (owner request 2026-10-27): persistent
metadata-only counting — known chats/users, membership, DM vs group,
ET-day activity, conservative seeding that never fakes "new", the
passive observer's classification, and the counts-only owner report.

Run: python3 test_usage.py"""
import asyncio
import datetime as real_dt
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
ext.TypeHandler = _DummyHandler
ext.ContextTypes = types.SimpleNamespace(DEFAULT_TYPE=object)
ext.filters = types.SimpleNamespace()
tg.ext = ext

sys.modules["telegram"] = tg
sys.modules["telegram.constants"] = constants
sys.modules["telegram.error"] = error
sys.modules["telegram.ext"] = ext

import store

fails = []


def check(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        fails.append(name)


def raw(sql, args=()):
    c = sqlite3.connect(store.DB)
    rows = c.execute(sql, args).fetchall()
    c.commit()
    c.close()
    return rows


# ============ Seeding: conservative, never fakes "new" ============
store._conn()  # create schema on the empty DB (seeds nothing)
raw("DELETE FROM usage_meta")
raw("DELETE FROM usage_chats")
raw("DELETE FROM usage_users")
OLD = 1700000000  # 2023-11-14 — real evidence timestamp, never "today"
c = sqlite3.connect(store.DB)
c.execute("INSERT INTO messages(chat_id,user_id,user_name,text,ts,message_id) VALUES(-1001, 101, 'x', 'hi', ?, 1)", (OLD,))
c.execute("INSERT INTO messages(chat_id,user_id,user_name,text,ts,message_id) VALUES(-1001, 101, 'x', 'again', ?, 2)", (OLD + 60,))
c.execute("INSERT INTO messages(chat_id,user_id,user_name,text,ts,message_id) VALUES(202, 202, 'y', 'dm', ?, 3)", (OLD,))
c.execute("INSERT INTO chat_settings(chat_id,key,value) VALUES(-3003, 'burn_alerts', 'on')")
c.execute("INSERT INTO user_lang(user_id,lang) VALUES(303, 'es')")
c.execute("INSERT INTO mod_groups(chat_id,title,requested_by,approved,ts) VALUES(-4004, 'T', 101, 1, ?)", (OLD,))
c.commit(); c.close()
store._usage_ready = False
store._conn()  # triggers the one-time seed

today = store.et_day()
counts = store.registry_counts()
row = raw("SELECT first_seen_ts, is_member, seeded FROM usage_chats WHERE chat_id=-1001")[0]
check("seeded chat keeps earliest message ts", row[0] == OLD)
check("seeded chat membership is UNKNOWN (NULL)", row[1] is None)
check("seeded chat flagged seeded", row[2] == 1)
urow = raw("SELECT first_seen_ts, first_seen_group_ts, first_seen_dm_ts, seeded FROM usage_users WHERE user_id=101")[0]
check("seeded group user keeps message ts + group marker", urow[0] == OLD and urow[1] == OLD and urow[2] is None and urow[3] == 1)
drow = raw("SELECT first_seen_dm_ts FROM usage_users WHERE user_id=202")[0]
check("seeded DM user (positive chat id) gets DM marker", drow[0] == OLD)
lrow = raw("SELECT seeded FROM usage_users WHERE user_id=303")[0]
check("user_lang-only user seeded + flagged", lrow and lrow[0] == 1)
check("seeded people are NEVER new today", counts["new_people_today"] == 0)
check("seeded groups are NEVER new today", counts["new_groups_today"] == 0)
check("seeded totals count people", counts["people_total"] == 3)
check("no group is a confirmed member yet", counts["groups_member"] == 0)
check("known-but-unconfirmed groups counted", counts["groups_unknown"] == 3)

# ============ Live observation ============
now = int(real_dt.datetime.now().timestamp())
store.observe_update(chat_id=-5001, chat_type="supergroup", user_id=501, kind="message", ts=now)
counts = store.registry_counts()
check("live group sighting confirms membership", counts["groups_member"] == 1)
check("live user is new today", counts["new_people_today"] == 1)
check("live group is new today", counts["new_groups_today"] == 1)
check("active people today counts the user", counts["people_active_today"] == 1)
check("active groups today counts the group", counts["groups_active_today"] == 1)
check("message interaction counted", counts["interactions_today"]["message"] == 1)

store.observe_update(chat_id=-5001, chat_type="supergroup", user_id=501, kind="command", ts=now)
counts = store.registry_counts()
check("repeat sighting dedupes the person", counts["people_total"] == 4 and counts["new_people_today"] == 1)
check("command interaction counted separately", counts["interactions_today"]["command"] == 1)
check("sighting row deduped per day", len(raw("SELECT * FROM usage_sightings WHERE chat_id=-5001 AND user_id=501 AND day=?", (today,))) == 1)

store.observe_update(chat_id=502, chat_type="private", user_id=502, kind="message", ts=now)
counts = store.registry_counts()
check("DM user counted as DM person", counts["people_dm_total"] == 2)
check("DM active today", counts["dm_active_today"] == 1)

store.observe_update(chat_id=-5001, chat_type="supergroup", user_id=9999, user_is_bot=True, kind="message", ts=now)
check("bot accounts never counted as people", store.registry_counts()["people_total"] == 5)

store.observe_update(chat_id=-5001, chat_type="supergroup", user_id=503, kind="message", record_user=False, ts=now)
check("join-service sighting records no user", store.registry_counts()["people_total"] == 5)

store.note_membership(-5001, False, ts=now)
counts = store.registry_counts()
check("membership flip to left", counts["groups_left"] == 1 and counts["groups_member"] == 0)
store.note_membership(-5001, True, ts=now)
counts = store.registry_counts()
check("membership flip back to member", counts["groups_member"] == 1 and counts["groups_left"] == 0)

# ET day boundary: just after ET midnight counts today; just before counts yesterday
start, _end = store._et_bounds(today)
store.observe_update(chat_id=-5001, chat_type="supergroup", user_id=504, kind="message", ts=start + 1800)
store.observe_update(chat_id=-5001, chat_type="supergroup", user_id=505, kind="message", ts=start - 1800)
counts = store.registry_counts()
check("ET-midnight+30m user is new today", counts["new_people_today"] == 3)
yday = (real_dt.datetime.strptime(today, "%Y-%m-%d") - real_dt.timedelta(days=1)).strftime("%Y-%m-%d")
ycounts = store.registry_counts(day=yday)
check("ET-midnight-30m user belongs to yesterday", ycounts["new_people_today"] == 1 and ycounts["people_active_today"] == 1)

# ============ Observer classification + handler ============
import bot

check("TypeHandler wired (stub provides it)", bot.TypeHandler is not None)


def NS(**kw):
    return types.SimpleNamespace(**kw)


cmd_msg = NS(text="/price", entities=[NS(type="bot_command", offset=0)], new_chat_members=None, left_chat_member=None)
check("entity command classified", bot._classify_update(NS(message=cmd_msg, callback_query=None, edited_message=None)) == "command")
plain = NS(text="hello", entities=[], new_chat_members=None, left_chat_member=None)
check("plain text classified message", bot._classify_update(NS(message=plain, callback_query=None, edited_message=None)) == "message")
slash = NS(text="/price", entities=None, new_chat_members=None, left_chat_member=None)
check("slash text classified command", bot._classify_update(NS(message=slash, callback_query=None, edited_message=None)) == "command")
check("callback classified button", bot._classify_update(NS(message=None, callback_query=NS(), edited_message=None)) == "button")
check("inline-only classified other", bot._classify_update(NS(message=None, callback_query=None, edited_message=None)) == "other")

CTX = NS(bot=NS(id=424242))
upd = NS(message=plain, callback_query=None, edited_message=None, my_chat_member=None,
         effective_chat=NS(id=-6001, type="supergroup"), effective_user=NS(id=601, is_bot=False))
before = store.registry_counts()
asyncio.run(bot.on_observe_update(upd, CTX))
after = store.registry_counts()
check("observer records the sighting", after["people_total"] == before["people_total"] + 1 and after["groups_member"] == before["groups_member"] + 1)

join_msg = NS(text=None, entities=[], new_chat_members=[NS()], left_chat_member=None)
upd = NS(message=join_msg, callback_query=None, edited_message=None, my_chat_member=None,
         effective_chat=NS(id=-6003, type="supergroup"), effective_user=NS(id=603, is_bot=False))
before = store.registry_counts()
asyncio.run(bot.on_observe_update(upd, CTX))
after = store.registry_counts()
check("observer: join service adds chat, not a person",
      after["people_total"] == before["people_total"] and len(raw("SELECT * FROM usage_chats WHERE chat_id=-6003")) == 1)

upd = NS(message=None, callback_query=None, edited_message=None,
         my_chat_member=NS(new_chat_member=NS(status="kicked")),
         effective_chat=NS(id=-6002, type="supergroup"), effective_user=NS(id=602, is_bot=False))
asyncio.run(bot.on_observe_update(upd, CTX))
check("observer: my_chat_member kicked flips membership off",
      raw("SELECT is_member FROM usage_chats WHERE chat_id=-6002")[0][0] == 0)

broken = NS(message=None, callback_query=None, edited_message=None, my_chat_member=None,
            effective_chat=None, effective_user=None)
asyncio.run(bot.on_observe_update(broken, CTX))
check("observer never raises on junk updates", True)

# ============ Report formatter: counts only ============
fixed = {
    "day": "2026-10-27", "groups_member": 12, "groups_unknown": 3, "groups_left": 1,
    "groups_active_today": 4, "new_groups_today": 1, "people_total": 231,
    "people_dm_total": 58, "people_group_total": 204, "people_active_today": 17,
    "dm_active_today": 3, "new_people_today": 2,
    "interactions_today": {"command": 61, "message": 74, "button": 7, "other": 0},
    "interactions_total": 142, "messages_logged": 3412,
}
legacy = {"groups": 9, "people_in_groups": 180, "dm_users": 40, "messages": 3412}
text = bot.format_usage_report(fixed, legacy, 12340, 200000)
check("report shows confirmed groups", "Groups I'm in: 12 confirmed" in text)
check("report shows unconfirmed + removed", "+3 known but unconfirmed" in text and "1 known to have removed me" in text)
check("report shows people + activity", "People known: 231" in text and "People active today: 17" in text and "New people today: 2" in text)
check("report shows interactions breakdown", "142" in text and "commands 61" in text and "button taps 7" in text)
check("report shows pot line labeled UTC estimate", "AI pot today (UTC day, estimate): 12,340 / 200,000 tokens" in text)
check("report keeps legacy view labeled secondary", "Older log-based view" in text)
check("report carries the honesty note", "stays invisible until it stirs" in text)
check("report contains NO names/usernames", "@" not in text and "title" not in text.lower())

# ============ Daily job: sends once at/after 7 PM ET, then dedupes ============
sent = []


class _FakeBot:
    id = 424242

    async def send_message(self, chat_id, text, parse_mode=None):
        sent.append((chat_id, text))


class _FakeDateTime(real_dt.datetime):
    @classmethod
    def now(cls, tz=None):
        return real_dt.datetime(2026, 10, 27, 20, 0, tzinfo=tz)


_real_bot_dt = bot.datetime
_real_et_day = store.et_day
bot.datetime = types.SimpleNamespace(datetime=_FakeDateTime, timezone=real_dt.timezone, timedelta=real_dt.timedelta)
store.et_day = lambda ts=None: "2026-10-27"
bot.OWNER_ID = 999
try:
    asyncio.run(bot.job_usage_report(NS(bot=_FakeBot())))
    asyncio.run(bot.job_usage_report(NS(bot=_FakeBot())))
finally:
    bot.datetime = _real_bot_dt
    store.et_day = _real_et_day
check("daily job sent exactly once", len(sent) == 1 and sent[0][0] == 999)
check("daily job persisted its last-sent day", store.get_setting(0, "usage_report_day") == "2026-10-27")

# ============ Combined all-bots report (Steve's ruling 2026-10-27) ============
_now = int(real_dt.datetime.now().timestamp())
_garuda_fresh = {"bot": "garuda", "ts": _now, "groups_logging": 3, "people_in_groups": 40,
                 "dm_users": 6, "messages_logged": 900, "pot_spent": 100, "pot_budget": 200000}
_prof_fresh = {"bot": "professor", "ts": _now, "groups_serving": 4,
               "group_questions_today": 6, "dm_askers_today": 2}
_do_fresh = {"bot": "do", "ts": _now, "groups_logging": 2, "people_in_groups": 30,
             "dm_users": 5, "messages_logged": 700}

combined = bot.format_combined_report(fixed, legacy, 12340, 200000,
                                      {"garuda": _garuda_fresh, "professor": _prof_fresh,
                                       "do": _do_fresh}, now_ts=_now)
check("combined: header covers all bots", "Daily usage — all bots" in combined)
check("combined: LUNC section counted live", "*LUNC Assistant*" in combined and "Groups I'm in: 12 confirmed" in combined)
check("combined: garuda counts + as-of", "*Garuda Assistant* — as of" in combined and "People seen talking in those groups: 40" in combined)
check("combined: professor counts", "Groups I'm serving: 4" in combined and "DM today (UTC, since its last restart): 2" in combined)
check("combined: do counts", "*DO Chain Assistant* — as of" in combined and "Messages currently logged: 700" in combined)
check("combined: no stale lines when all fresh", "No fresh report" not in combined)
check("combined: contains NO names/usernames", "@" not in combined)

mixed = bot.format_combined_report(fixed, legacy, 12340, 200000,
                                   {"garuda": dict(_garuda_fresh, ts=_now - 27 * 3600),
                                    "professor": None, "do": _do_fresh}, now_ts=_now)
check("combined: stale + missing bots each get the honest line", mixed.count("No fresh report") == 2)
check("combined: missing bot says last seen never", "No fresh report — last seen never" in mixed)
check("combined: fresh bot still shows counts in mixed", "Messages currently logged: 700" in mixed)

# Job-level: configured + reads OK -> combined DM; reads raise -> solo fallback.
_sent2 = []


class _FakeBot2(_FakeBot):
    async def send_message(self, chat_id, text, parse_mode=None):
        _sent2.append((chat_id, text))


async def _fake_read_ok(name):
    return {"garuda": _garuda_fresh, "professor": _prof_fresh, "do": _do_fresh}[name]


async def _fake_read_boom(name):
    raise RuntimeError("upstash unreachable")


_sr = bot.stats_report
_real_read_bot = _sr.read_bot
os.environ["UPSTASH_STATS_URL"] = "https://stats.example.test"
os.environ["UPSTASH_STATS_TOKEN"] = "tok123"
bot.datetime = types.SimpleNamespace(datetime=_FakeDateTime, timezone=real_dt.timezone, timedelta=real_dt.timedelta)
store.et_day = lambda ts=None: "2026-10-27"
bot.OWNER_ID = 999
try:
    _sr.read_bot = _fake_read_ok
    store.set_setting(0, "usage_report_day", "")
    asyncio.run(bot.job_usage_report(NS(bot=_FakeBot2())))
    check("job sends the COMBINED report when reads work",
          len(_sent2) == 1 and "Daily usage — all bots" in _sent2[0][1])
    _sr.read_bot = _fake_read_boom
    store.set_setting(0, "usage_report_day", "")
    asyncio.run(bot.job_usage_report(NS(bot=_FakeBot2())))
    check("job falls back to the SOLO report when reads fail entirely",
          len(_sent2) == 2 and "LUNC Assistant — daily usage" in _sent2[1][1]
          and "all bots" not in _sent2[1][1])
finally:
    _sr.read_bot = _real_read_bot
    os.environ.pop("UPSTASH_STATS_URL", None)
    os.environ.pop("UPSTASH_STATS_TOKEN", None)
    bot.datetime = _real_bot_dt
    store.et_day = _real_et_day

print()
print("FAILURES:", fails if fails else "none")
sys.exit(1 if fails else 0)
