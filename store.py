import sqlite3, os, time
DB = os.getenv("DB_PATH", "data/messages.db")
os.makedirs(os.path.dirname(DB) or ".", exist_ok=True)
RETENTION_DAYS = int(os.getenv("RETENTION_DAYS", "7"))

def _conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS messages(
        id INTEGER PRIMARY KEY, chat_id INTEGER, user_id INTEGER, user_name TEXT,
        text TEXT, ts INTEGER, message_id INTEGER)""")
    c.execute("""CREATE TABLE IF NOT EXISTS catchup(
        chat_id INTEGER, user_id INTEGER, last_seen_id INTEGER, PRIMARY KEY(chat_id,user_id))""")
    c.execute("""CREATE TABLE IF NOT EXISTS chat_settings(
        chat_id INTEGER, key TEXT, value TEXT, PRIMARY KEY(chat_id,key))""")
    c.execute("""CREATE TABLE IF NOT EXISTS user_lang(
        user_id INTEGER PRIMARY KEY, lang TEXT)""")
    _ensure_rank_tables(c)
    _ensure_mod_tables(c)
    _ensure_usage(c)
    return c

# --- Per-user language (personal choice: never a group setting) ---
def get_user_lang(user_id):
    c = _conn()
    r = c.execute("SELECT lang FROM user_lang WHERE user_id=?", (user_id,)).fetchone()
    c.close()
    return r["lang"] if r else "en"

def set_user_lang(user_id, lang):
    c = _conn()
    c.execute("INSERT INTO user_lang(user_id,lang) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET lang=excluded.lang", (user_id, lang))
    c.commit(); c.close()

# --- Per-chat settings (burn alerts etc.) ---
# Keys: burn_alerts (on/off, default OFF), burn_daily, burn_big, burn_rate (on/off)
BURN_DEFAULTS = {"burn_alerts": "off", "burn_daily": "on", "burn_big": "on", "burn_rate": "on"}

def get_setting(chat_id, key, default=None):
    c = _conn()
    r = c.execute("SELECT value FROM chat_settings WHERE chat_id=? AND key=?", (chat_id, key)).fetchone()
    c.close()
    if r: return r["value"]
    if default is not None: return default
    return BURN_DEFAULTS.get(key)

def set_setting(chat_id, key, value):
    c = _conn()
    c.execute("INSERT INTO chat_settings(chat_id,key,value) VALUES(?,?,?) ON CONFLICT(chat_id,key) DO UPDATE SET value=excluded.value", (chat_id, key, str(value)))
    c.commit(); c.close()

# --- Per-group AI switch (default ON) ---
# A group's own admins can turn AI off for their group (/aioff): the
# ai_guard then blocks every AI path in that chat before rank, caps,
# or the pot are even consulted. Stored as a normal chat setting;
# never set = AI on. Private chats are not affected by this switch.
def ai_enabled(chat_id):
    return get_setting(chat_id, "ai_group", "on") != "off"


def set_ai_enabled(chat_id, on):
    set_setting(chat_id, "ai_group", "on" if on else "off")


BURN_KEYS = ["burn_alerts", "burn_daily", "burn_big", "burn_rate"]
def burn_settings(chat_id):
    return {k: get_setting(chat_id, k) for k in BURN_KEYS}

def chats_with_burn_on():
    c = _conn()
    rows = c.execute("SELECT chat_id FROM chat_settings WHERE key='burn_alerts' AND value='on'").fetchall()
    c.close()
    return [r["chat_id"] for r in rows]

# --- Gov alerts (same pattern as burn) ---
GOV_DEFAULTS = {"gov_alerts": "off", "gov_new": "on", "gov_ending": "on", "gov_result": "on"}
_orig_burn_defaults = dict(BURN_DEFAULTS)
BURN_DEFAULTS.update(GOV_DEFAULTS)  # get_setting falls back across both sets

def gov_settings(chat_id):
    return {k: get_setting(chat_id, k) for k in GOV_DEFAULTS}

def chats_with_gov_on():
    c = _conn()
    rows = c.execute("SELECT chat_id FROM chat_settings WHERE key='gov_alerts' AND value='on'").fetchall()
    c.close()
    return [r["chat_id"] for r in rows]

# --- Validator watchlist (per chat) ---
def _ensure_val_table(c):
    c.execute("""CREATE TABLE IF NOT EXISTS watched_validators(
        chat_id INTEGER, valoper TEXT, moniker TEXT, snapshot TEXT,
        PRIMARY KEY(chat_id, valoper))""")

def watch_validator(chat_id, valoper, moniker, snapshot_json):
    c = _conn(); _ensure_val_table(c)
    c.execute("INSERT INTO watched_validators(chat_id,valoper,moniker,snapshot) VALUES(?,?,?,?) ON CONFLICT(chat_id,valoper) DO UPDATE SET moniker=excluded.moniker, snapshot=excluded.snapshot", (chat_id, valoper, moniker, snapshot_json))
    c.commit(); c.close()

def unwatch_validator(chat_id, valoper):
    c = _conn(); _ensure_val_table(c)
    cur = c.execute("DELETE FROM watched_validators WHERE chat_id=? AND valoper=?", (chat_id, valoper))
    c.commit(); n = cur.rowcount; c.close(); return n

def list_watched(chat_id=None):
    c = _conn(); _ensure_val_table(c)
    if chat_id is None:
        rows = c.execute("SELECT * FROM watched_validators").fetchall()
    else:
        rows = c.execute("SELECT * FROM watched_validators WHERE chat_id=?", (chat_id,)).fetchall()
    c.close(); return [dict(r) for r in rows]

def update_snapshot(chat_id, valoper, snapshot_json):
    c = _conn(); _ensure_val_table(c)
    c.execute("UPDATE watched_validators SET snapshot=? WHERE chat_id=? AND valoper=?", (snapshot_json, chat_id, valoper))
    c.commit(); c.close()

def log_message(chat_id, user_id, user_name, text, message_id):
    if not text: return
    c = _conn()
    now = int(time.time())
    c.execute("INSERT INTO messages(chat_id,user_id,user_name,text,ts,message_id) VALUES(?,?,?,?,?,?)",
              (chat_id, user_id, user_name, text, now, message_id))
    c.execute("DELETE FROM messages WHERE ts < ?", (now - RETENTION_DAYS*86400,))
    # Rank day: one row per user per UTC day they actually chatted. Commands
    # are never logged, so querying can never earn rank.
    c.execute("INSERT OR IGNORE INTO rank_days(chat_id,user_id,day) VALUES(?,?,date(?, 'unixepoch'))",
              (chat_id, user_id, now))
    c.commit(); c.close()

def get_messages(chat_id, limit=200, since_ts=None, after_id=None):
    c = _conn()
    q = "SELECT * FROM messages WHERE chat_id=?"
    args = [chat_id]
    if since_ts: q += " AND ts>=?"; args.append(since_ts)
    if after_id: q += " AND id>?"; args.append(after_id)
    q += " ORDER BY id DESC LIMIT ?"; args.append(limit)
    rows = [dict(r) for r in c.execute(q, args).fetchall()]
    c.close()
    return list(reversed(rows))

def set_catchup(chat_id, user_id):
    rows = get_messages(chat_id, limit=1)
    last = rows[-1]["id"] if rows else 0
    # get true max id
    c = _conn()
    row = c.execute("SELECT MAX(id) as m FROM messages WHERE chat_id=?", (chat_id,)).fetchone()
    last = row["m"] or 0
    c.execute("INSERT INTO catchup(chat_id,user_id,last_seen_id) VALUES(?,?,?) ON CONFLICT(chat_id,user_id) DO UPDATE SET last_seen_id=excluded.last_seen_id", (chat_id, user_id, last))
    c.commit(); c.close()
    return last

def get_catchup_id(chat_id, user_id):
    c = _conn()
    r = c.execute("SELECT last_seen_id FROM catchup WHERE chat_id=? AND user_id=?", (chat_id, user_id)).fetchone()
    c.close()
    return r["last_seen_id"] if r else None

def usage_counts():
    """Owner-only usage snapshot: distinct chats/people the bot has actually seen."""
    c = _conn()
    def q(sql):
        r = c.execute(sql).fetchone()
        return r[0] if r else 0
    out = {
        "groups": q("SELECT COUNT(DISTINCT chat_id) FROM messages WHERE chat_id < 0"),
        "people_in_groups": q("SELECT COUNT(DISTINCT user_id) FROM messages WHERE chat_id < 0 AND user_id IS NOT NULL"),
        "dm_users": q("SELECT COUNT(DISTINCT chat_id) FROM (SELECT chat_id FROM chat_settings WHERE chat_id > 0 UNION SELECT chat_id FROM catchup WHERE chat_id > 0)"),
        "messages": q("SELECT COUNT(*) FROM messages"),
    }
    c.close()
    return out

# --- Ranks: who may use AI queries ---
# Rank is earned by chatting on distinct UTC days in a group (one rank-day
# per calendar day max, however many messages). Raw message counts can be
# farmed by spamming; distinct days cannot. Commands are never logged, so
# querying can never earn rank.
#   rank 0: fewer than RANK_DAYS_1 distinct days (includes never seen) — 2 AI queries/day
#   rank 1: RANK_DAYS_1..RANK_DAYS_2-1 days — 4 AI queries/day
#   rank 2: RANK_DAYS_2+ days — 6 AI queries/day
# (Daily caps live in ratelimit.py — owner decision 2026-10-25.)
# A manual override (owner-set) always wins over the earned rank.
# The DB lives on a persistent volume (/data), so rank history survives
# redeploys; the owner can still adjust anyone with /rankset.
RANK_DAYS_1 = 3
RANK_DAYS_2 = 30

def _ensure_rank_tables(c):
    c.execute("""CREATE TABLE IF NOT EXISTS rank_days(
        chat_id INTEGER, user_id INTEGER, day TEXT,
        PRIMARY KEY(chat_id, user_id, day))""")
    c.execute("""CREATE TABLE IF NOT EXISTS rank_override(
        chat_id INTEGER, user_id INTEGER, rank INTEGER, set_by INTEGER, ts INTEGER,
        PRIMARY KEY(chat_id, user_id))""")
    # Idempotent seed from the surviving message log (helps after a restart;
    # the DB itself persists across redeploys via the /data volume).
    c.execute("""INSERT OR IGNORE INTO rank_days(chat_id, user_id, day)
                 SELECT chat_id, user_id, date(ts, 'unixepoch')
                 FROM messages WHERE user_id IS NOT NULL""")

def _rank_from_days(days):
    return 2 if days >= RANK_DAYS_2 else (1 if days >= RANK_DAYS_1 else 0)

def days_active(chat_id, user_id):
    c = _conn()
    r = c.execute("SELECT COUNT(*) FROM rank_days WHERE chat_id=? AND user_id=?", (chat_id, user_id)).fetchone()
    c.close()
    return r[0]

def days_active_anywhere(user_id):
    c = _conn()
    r = c.execute("SELECT COUNT(DISTINCT day) FROM rank_days WHERE user_id=?", (user_id,)).fetchone()
    c.close()
    return r[0]

def rank_info(chat_id, user_id):
    """(rank, days_active, manual_override_or_None) for one group chat."""
    c = _conn()
    r = c.execute("SELECT rank FROM rank_override WHERE chat_id=? AND user_id=?", (chat_id, user_id)).fetchone()
    c.close()
    if r is not None:
        return r["rank"], days_active(chat_id, user_id), r["rank"]
    days = days_active(chat_id, user_id)
    return _rank_from_days(days), days, None

def rank_for(chat_id, user_id):
    return rank_info(chat_id, user_id)[0]

def rank_anywhere(user_id):
    """DM rank: earned days across all logged groups, no per-chat override."""
    return _rank_from_days(days_active_anywhere(user_id))

def set_rank_override(chat_id, user_id, rank, set_by):
    if rank not in (0, 1, 2):
        raise ValueError("rank must be 0, 1 or 2")
    c = _conn()
    c.execute("INSERT INTO rank_override(chat_id,user_id,rank,set_by,ts) VALUES(?,?,?,?,?) ON CONFLICT(chat_id,user_id) DO UPDATE SET rank=excluded.rank, set_by=excluded.set_by, ts=excluded.ts",
              (chat_id, user_id, rank, set_by, int(time.time())))
    c.commit(); c.close()

def clear_rank_override(chat_id, user_id):
    c = _conn()
    cur = c.execute("DELETE FROM rank_override WHERE chat_id=? AND user_id=?", (chat_id, user_id))
    c.commit(); n = cur.rowcount; c.close(); return n


# --- Group protection (Phase 1 moderation, 2026-10-25) ---
# Cosmobot-style setup for Luna Classic groups, owner-approved design:
# groups opt in via a request the OWNER approves; registered groups get
# a captcha gate for new joiners, a shared global scam-ban list, and
# first-message link removal. All state lives in this same DB, which
# sits on a persistent volume — the registry and ban list survive
# redeploys.

def _ensure_mod_tables(c):
    c.execute("""CREATE TABLE IF NOT EXISTS mod_groups(
        chat_id INTEGER PRIMARY KEY, title TEXT, requested_by INTEGER,
        approved INTEGER, ts INTEGER)""")
    c.execute("""CREATE TABLE IF NOT EXISTS gbans(
        user_id INTEGER PRIMARY KEY, reason TEXT, banned_by INTEGER, ts INTEGER)""")
    c.execute("""CREATE TABLE IF NOT EXISTS elevated_users(
        user_id INTEGER PRIMARY KEY, added_by INTEGER, ts INTEGER)""")
    c.execute("""CREATE TABLE IF NOT EXISTS captcha_pending(
        chat_id INTEGER, user_id INTEGER, deadline INTEGER,
        PRIMARY KEY(chat_id, user_id))""")
    c.execute("""CREATE TABLE IF NOT EXISTS members_verified(
        chat_id INTEGER, user_id INTEGER, ts INTEGER,
        PRIMARY KEY(chat_id, user_id))""")
    c.execute("""CREATE TABLE IF NOT EXISTS first_msg_seen(
        chat_id INTEGER, user_id INTEGER,
        PRIMARY KEY(chat_id, user_id))""")
    c.execute("""CREATE TABLE IF NOT EXISTS blacklist(
        word TEXT PRIMARY KEY, added_by INTEGER, ts INTEGER)""")
    c.execute("""CREATE TABLE IF NOT EXISTS ai_bans(
        user_id INTEGER PRIMARY KEY, reason TEXT, banned_by INTEGER, ts INTEGER)""")
    c.execute("""CREATE TABLE IF NOT EXISTS mod_log(
        id INTEGER PRIMARY KEY AUTOINCREMENT, actor INTEGER, action TEXT,
        target INTEGER, chat_id INTEGER, detail TEXT, ts INTEGER)""")
    c.execute("""CREATE TABLE IF NOT EXISTS fresh_holds(
        chat_id INTEGER, user_id INTEGER, until_ts INTEGER,
        PRIMARY KEY(chat_id, user_id))""")
    c.execute("""CREATE TABLE IF NOT EXISTS appeals(
        user_id INTEGER PRIMARY KEY, kind TEXT, ts INTEGER)""")
    c.execute("""CREATE TABLE IF NOT EXISTS captcha_strikes(
        chat_id INTEGER, user_id INTEGER, strikes INTEGER DEFAULT 0,
        PRIMARY KEY(chat_id, user_id))""")
    c.execute("""CREATE TABLE IF NOT EXISTS faq(
        chat_id INTEGER, question TEXT, answer TEXT, added_by INTEGER, ts INTEGER,
        PRIMARY KEY(chat_id, question))""")

import time as _time

def mod_request_group(chat_id, title, requested_by):
    c = _conn()
    c.execute("""INSERT INTO mod_groups(chat_id, title, requested_by, approved, ts)
                 VALUES(?, ?, ?, 0, ?)
                 ON CONFLICT(chat_id) DO UPDATE SET title=excluded.title""",
              (chat_id, title, requested_by, int(_time.time())))
    c.commit(); c.close()

def mod_approve_group(chat_id):
    c = _conn()
    cur = c.execute("UPDATE mod_groups SET approved=1 WHERE chat_id=?", (chat_id,))
    c.commit(); n = cur.rowcount; c.close(); return n

def mod_remove_group(chat_id):
    c = _conn()
    cur = c.execute("DELETE FROM mod_groups WHERE chat_id=?", (chat_id,))
    c.commit(); n = cur.rowcount; c.close(); return n

def mod_group(chat_id):
    c = _conn()
    r = c.execute("SELECT * FROM mod_groups WHERE chat_id=?", (chat_id,)).fetchone()
    c.close(); return r

def mod_is_protected(chat_id):
    r = mod_group(chat_id)
    return bool(r and r["approved"])

def mod_groups(approved_only=True):
    c = _conn()
    if approved_only:
        rows = c.execute("SELECT * FROM mod_groups WHERE approved=1 ORDER BY chat_id").fetchall()
    else:
        rows = c.execute("SELECT * FROM mod_groups ORDER BY approved, chat_id").fetchall()
    c.close(); return rows

def gban_add(user_id, reason, banned_by):
    c = _conn()
    c.execute("""INSERT INTO gbans(user_id, reason, banned_by, ts) VALUES(?, ?, ?, ?)
                 ON CONFLICT(user_id) DO UPDATE SET reason=excluded.reason,
                 banned_by=excluded.banned_by, ts=excluded.ts""",
              (user_id, reason or "", banned_by, int(_time.time())))
    c.commit(); c.close()

def gban_remove(user_id):
    c = _conn()
    cur = c.execute("DELETE FROM gbans WHERE user_id=?", (user_id,))
    c.commit(); n = cur.rowcount; c.close(); return n

def gban_get(user_id):
    c = _conn()
    r = c.execute("SELECT * FROM gbans WHERE user_id=?", (user_id,)).fetchone()
    c.close(); return r

def gban_all():
    c = _conn()
    rows = c.execute("SELECT * FROM gbans ORDER BY ts DESC").fetchall()
    c.close(); return rows

def elevated_add(user_id, added_by):
    c = _conn()
    c.execute("""INSERT INTO elevated_users(user_id, added_by, ts) VALUES(?, ?, ?)
                 ON CONFLICT(user_id) DO NOTHING""",
              (user_id, added_by, int(_time.time())))
    c.commit(); c.close()

def elevated_remove(user_id):
    c = _conn()
    cur = c.execute("DELETE FROM elevated_users WHERE user_id=?", (user_id,))
    c.commit(); n = cur.rowcount; c.close(); return n

def is_elevated(user_id):
    c = _conn()
    r = c.execute("SELECT user_id FROM elevated_users WHERE user_id=?", (user_id,)).fetchone()
    c.close(); return r is not None

def elevated_all():
    c = _conn()
    rows = c.execute("SELECT * FROM elevated_users ORDER BY ts").fetchall()
    c.close(); return rows

def captcha_start(chat_id, user_id, deadline):
    c = _conn()
    c.execute("""INSERT INTO captcha_pending(chat_id, user_id, deadline) VALUES(?, ?, ?)
                 ON CONFLICT(chat_id, user_id) DO UPDATE SET deadline=excluded.deadline""",
              (chat_id, user_id, deadline))
    c.commit(); c.close()

def captcha_get(chat_id, user_id):
    c = _conn()
    r = c.execute("SELECT * FROM captcha_pending WHERE chat_id=? AND user_id=?",
                  (chat_id, user_id)).fetchone()
    c.close(); return r

def captcha_for_user(user_id):
    c = _conn()
    r = c.execute("SELECT * FROM captcha_pending WHERE user_id=? ORDER BY deadline LIMIT 1",
                  (user_id,)).fetchone()
    c.close(); return r

def captcha_clear(chat_id, user_id):
    c = _conn()
    c.execute("DELETE FROM captcha_pending WHERE chat_id=? AND user_id=?", (chat_id, user_id))
    c.commit(); c.close()

def captcha_expired(now_ts):
    c = _conn()
    rows = c.execute("SELECT * FROM captcha_pending WHERE deadline < ?", (now_ts,)).fetchall()
    c.close(); return rows

def member_verify(chat_id, user_id):
    c = _conn()
    c.execute("""INSERT INTO members_verified(chat_id, user_id, ts) VALUES(?, ?, ?)
                 ON CONFLICT(chat_id, user_id) DO NOTHING""",
              (chat_id, user_id, int(_time.time())))
    c.commit(); c.close()

def member_is_verified(chat_id, user_id):
    c = _conn()
    r = c.execute("SELECT user_id FROM members_verified WHERE chat_id=? AND user_id=?",
                  (chat_id, user_id)).fetchone()
    c.close(); return r is not None

def first_msg_mark(chat_id, user_id):
    """True when this is the user's first tracked message in the chat."""
    c = _conn()
    cur = c.execute("INSERT OR IGNORE INTO first_msg_seen(chat_id, user_id) VALUES(?, ?)",
                    (chat_id, user_id))
    c.commit(); n = cur.rowcount; c.close(); return n > 0

# --- AI bans + moderation log (2026-10-25): an AI ban blocks ONLY the
# AI features (the ai_guard checks it) — the user keeps every simple
# command and can still chat. The mod log is the permanent record of
# who did what; it is what makes moderator power auditable.

def ai_ban_add(user_id, reason, banned_by):
    c = _conn()
    c.execute("""INSERT INTO ai_bans(user_id, reason, banned_by, ts) VALUES(?, ?, ?, ?)
                 ON CONFLICT(user_id) DO UPDATE SET reason=excluded.reason,
                 banned_by=excluded.banned_by, ts=excluded.ts""",
              (user_id, reason or "", banned_by, int(_time.time())))
    c.commit(); c.close()

def ai_ban_remove(user_id):
    c = _conn()
    cur = c.execute("DELETE FROM ai_bans WHERE user_id=?", (user_id,))
    c.commit(); n = cur.rowcount; c.close(); return n

def ai_ban_get(user_id):
    c = _conn()
    r = c.execute("SELECT * FROM ai_bans WHERE user_id=?", (user_id,)).fetchone()
    c.close(); return r

def is_ai_banned(user_id):
    return ai_ban_get(user_id) is not None

def ai_ban_all():
    c = _conn()
    rows = c.execute("SELECT * FROM ai_bans ORDER BY ts DESC").fetchall()
    c.close(); return rows

def mod_log_add(actor, action, target, chat_id, detail):
    c = _conn()
    c.execute("INSERT INTO mod_log(actor, action, target, chat_id, detail, ts) VALUES(?, ?, ?, ?, ?, ?)",
              (actor, action, target, chat_id, detail or "", int(_time.time())))
    c.commit(); c.close()

def mod_log_recent(limit=20):
    c = _conn()
    rows = c.execute("SELECT * FROM mod_log ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()
    c.close(); return rows

def mod_action_count(actor, action, since_ts):
    c = _conn()
    n = c.execute("SELECT COUNT(*) FROM mod_log WHERE actor=? AND action=? AND ts>=?",
                  (actor, action, int(since_ts))).fetchone()[0]
    c.close(); return n

# --- Fresh-account holds + ban appeals (2026-10-25 security round 2) ---

def fresh_add(chat_id, user_id, until_ts):
    c = _conn()
    c.execute("""INSERT INTO fresh_holds(chat_id, user_id, until_ts) VALUES(?, ?, ?)
                 ON CONFLICT(chat_id, user_id) DO UPDATE SET until_ts=excluded.until_ts""",
              (chat_id, user_id, int(until_ts)))
    c.commit(); c.close()

def fresh_get(chat_id, user_id):
    c = _conn()
    r = c.execute("SELECT * FROM fresh_holds WHERE chat_id=? AND user_id=?",
                  (chat_id, user_id)).fetchone()
    c.close(); return r

def fresh_remove(chat_id, user_id):
    c = _conn()
    cur = c.execute("DELETE FROM fresh_holds WHERE chat_id=? AND user_id=?", (chat_id, user_id))
    c.commit(); n = cur.rowcount; c.close(); return n

def fresh_due(now_ts):
    c = _conn()
    rows = c.execute("SELECT * FROM fresh_holds WHERE until_ts<=?", (int(now_ts),)).fetchall()
    c.close(); return rows

def appeal_last(user_id):
    c = _conn()
    r = c.execute("SELECT * FROM appeals WHERE user_id=?", (user_id,)).fetchone()
    c.close(); return r

def appeal_record(user_id, kind):
    c = _conn()
    c.execute("""INSERT INTO appeals(user_id, kind, ts) VALUES(?, ?, ?)
                 ON CONFLICT(user_id) DO UPDATE SET kind=excluded.kind, ts=excluded.ts""",
              (user_id, kind, int(_time.time())))
    c.commit(); c.close()

# --- Captcha strikes + message lookup (2026-10-25 final fixes round) ---

def captcha_strike_add(chat_id, user_id):
    """Record one failed captcha attempt; returns the new strike count."""
    c = _conn()
    c.execute("""INSERT INTO captcha_strikes(chat_id, user_id, strikes) VALUES(?, ?, 1)
                 ON CONFLICT(chat_id, user_id) DO UPDATE SET strikes=strikes+1""",
              (chat_id, user_id))
    row = c.execute("SELECT strikes FROM captcha_strikes WHERE chat_id=? AND user_id=?",
                    (chat_id, user_id)).fetchone()
    c.commit(); c.close()
    return row[0] if row else 1

def captcha_strikes_clear(chat_id, user_id):
    c = _conn()
    c.execute("DELETE FROM captcha_strikes WHERE chat_id=? AND user_id=?", (chat_id, user_id))
    c.commit(); c.close()

def message_text(chat_id, message_id):
    """The originally logged text of a message (for edit comparison)."""
    c = _conn()
    r = c.execute("""SELECT text FROM messages WHERE chat_id=? AND message_id=?
                     ORDER BY id DESC LIMIT 1""", (chat_id, message_id)).fetchone()
    c.close()
    return r[0] if r else None

# --- Phase 2 moderation (2026-10-25): blacklist, scam alerts, stats ---

def blacklist_add(word, added_by):
    c = _conn()
    c.execute("""INSERT INTO blacklist(word, added_by, ts) VALUES(?, ?, ?)
                 ON CONFLICT(word) DO NOTHING""",
              (word, added_by, int(_time.time())))
    c.commit(); c.close()

def blacklist_remove(word):
    c = _conn()
    cur = c.execute("DELETE FROM blacklist WHERE word=?", (word,))
    c.commit(); n = cur.rowcount; c.close(); return n

def blacklist_all():
    c = _conn()
    rows = c.execute("SELECT word FROM blacklist ORDER BY word").fetchall()
    c.close(); return [r["word"] for r in rows]

def scam_alerts_enabled(chat_id):
    return get_setting(chat_id, "scam_alerts", "off") == "on"

def set_scam_alerts(chat_id, on):
    set_setting(chat_id, "scam_alerts", "on" if on else "off")

def scam_last(chat_id):
    try:
        return int(get_setting(chat_id, "scam_last", "0") or 0)
    except ValueError:
        return 0

def set_scam_last(chat_id, ts):
    set_setting(chat_id, "scam_last", str(int(ts)))

def mod_stats():
    c = _conn()
    def n(sql):
        return c.execute(sql).fetchone()[0]
    stats = {
        "groups_protected": n("SELECT COUNT(*) FROM mod_groups WHERE approved=1"),
        "groups_pending": n("SELECT COUNT(*) FROM mod_groups WHERE approved=0"),
        "gbans": n("SELECT COUNT(*) FROM gbans"),
        "ai_bans": n("SELECT COUNT(*) FROM ai_bans"),
        "elevated": n("SELECT COUNT(*) FROM elevated_users"),
        "verified": n("SELECT COUNT(*) FROM members_verified"),
        "pending": n("SELECT COUNT(*) FROM captcha_pending"),
    }
    c.close(); return stats

# --- Per-group FAQ (2026-10-25) ---

def faq_add(chat_id, question, answer, added_by):
    c = _conn()
    c.execute("""INSERT INTO faq(chat_id, question, answer, added_by, ts) VALUES(?, ?, ?, ?, ?)
                 ON CONFLICT(chat_id, question) DO UPDATE SET answer=excluded.answer,
                 added_by=excluded.added_by, ts=excluded.ts""",
              (chat_id, question, answer, added_by, int(_time.time())))
    c.commit(); c.close()

def faq_remove(chat_id, question):
    c = _conn()
    cur = c.execute("DELETE FROM faq WHERE chat_id=? AND question=?", (chat_id, question))
    c.commit(); n = cur.rowcount; c.close(); return n

def faq_get(chat_id, question):
    c = _conn()
    r = c.execute("SELECT answer FROM faq WHERE chat_id=? AND question=?",
                  (chat_id, question)).fetchone()
    c.close(); return r["answer"] if r else None

def faq_list(chat_id):
    c = _conn()
    rows = c.execute("SELECT question FROM faq WHERE chat_id=? ORDER BY question",
                     (chat_id,)).fetchall()
    c.close(); return [r["question"] for r in rows]

def pending_groups():
    c = _conn()
    rows = c.execute("SELECT * FROM mod_groups WHERE approved=0 ORDER BY chat_id").fetchall()
    c.close(); return rows

# --- GitHub PR watch (2026-10-25) ---
# Per-chat subscriptions: which repos a chat follows for PR news, and
# the forum topic (thread id) the enabling command was run in, if any.
# The master switch is a normal chat setting (pr_alerts, default OFF),
# same pattern as burn/gov alerts. Poller cursors/snapshots live in
# pr_repo_state, one JSON blob per repo, so restarts never re-post
# history. Only group config + cursors are stored — no message data.

def _ensure_pr_tables(c):
    c.execute("""CREATE TABLE IF NOT EXISTS pr_subscriptions(
        chat_id INTEGER, repo TEXT, thread_id INTEGER,
        PRIMARY KEY(chat_id, repo))""")
    c.execute("""CREATE TABLE IF NOT EXISTS pr_repo_state(
        repo TEXT PRIMARY KEY, state TEXT, updated INTEGER)""")

def pr_alerts_enabled(chat_id):
    return get_setting(chat_id, "pr_alerts", "off") == "on"

def set_pr_alerts(chat_id, on):
    set_setting(chat_id, "pr_alerts", "on" if on else "off")

def chats_with_pr_on():
    c = _conn()
    rows = c.execute("SELECT chat_id FROM chat_settings WHERE key='pr_alerts' AND value='on'").fetchall()
    c.close()
    return [r["chat_id"] for r in rows]

def pr_watch_add(chat_id, repo, thread_id=None):
    c = _conn(); _ensure_pr_tables(c)
    c.execute("""INSERT INTO pr_subscriptions(chat_id, repo, thread_id) VALUES(?,?,?)
                 ON CONFLICT(chat_id, repo) DO UPDATE SET
                 thread_id=COALESCE(excluded.thread_id, pr_subscriptions.thread_id)""",
              (chat_id, repo, thread_id))
    c.commit(); c.close()

def pr_watch_remove(chat_id, repo):
    c = _conn(); _ensure_pr_tables(c)
    cur = c.execute("DELETE FROM pr_subscriptions WHERE chat_id=? AND repo=?", (chat_id, repo))
    c.commit(); n = cur.rowcount; c.close(); return n

def pr_watch_list(chat_id=None):
    c = _conn(); _ensure_pr_tables(c)
    if chat_id is None:
        rows = c.execute("SELECT * FROM pr_subscriptions ORDER BY chat_id, repo").fetchall()
    else:
        rows = c.execute("SELECT * FROM pr_subscriptions WHERE chat_id=? ORDER BY repo", (chat_id,)).fetchall()
    c.close(); return [dict(r) for r in rows]

def pr_active_subscriptions():
    """Subscription rows whose chat actually has PR alerts switched ON."""
    c = _conn(); _ensure_pr_tables(c)
    rows = c.execute("""SELECT s.* FROM pr_subscriptions s
                        JOIN chat_settings cs ON cs.chat_id = s.chat_id
                        AND cs.key = 'pr_alerts' AND cs.value = 'on'
                        ORDER BY s.repo, s.chat_id""").fetchall()
    c.close(); return [dict(r) for r in rows]

import json as _json

def pr_get_state(repo):
    c = _conn(); _ensure_pr_tables(c)
    r = c.execute("SELECT state FROM pr_repo_state WHERE repo=?", (repo,)).fetchone()
    c.close()
    if not r: return None
    try: return _json.loads(r["state"])
    except Exception: return None

def pr_set_state(repo, state_dict):
    c = _conn(); _ensure_pr_tables(c)
    c.execute("""INSERT INTO pr_repo_state(repo, state, updated) VALUES(?,?,?)
                 ON CONFLICT(repo) DO UPDATE SET state=excluded.state, updated=excluded.updated""",
              (repo, _json.dumps(state_dict), int(_time.time())))
    c.commit(); c.close()

# --- Usage registry (2026-10-27, owner request: "how many people are
# using it and how many groups it's in", with a daily update) ---
# Persistent, METADATA-ONLY counting on the same /data SQLite DB.
# What is stored: chat ids + chat TYPE, user ids, first/last-seen
# timestamps, bot-membership state, per-day activity rows, and daily
# interaction counters by broad kind (command / message / button /
# other). What is NEVER stored here: message text, user names,
# usernames, chat titles. Counts only — the owner report and /botstats
# show aggregates, never names.
#
# Honesty rules (the report wording repeats them):
# - Telegram gives a bot NO way to enumerate its chats or subscribers.
#   The registry only knows what the bot has actually SEEN: a group
#   that never sends anything and predates tracking stays invisible
#   until it stirs.
# - The registry was seeded once from pre-existing DB evidence (see
#   _seed_usage). Seeded rows are flagged seeded=1 and are NEVER
#   reported as "new today" — they existed before tracking; only
#   their earliest genuine evidence timestamps (e.g. the message log)
#   are kept. Seeded chats start is_member=NULL (unknown): a past
#   sighting does not prove the bot is still in the group.
# - "Active today" counts only live observations since tracking
#   began, on America/New_York calendar days.

import datetime as _dt
try:
    from zoneinfo import ZoneInfo as _ZoneInfo
    _ET = _ZoneInfo("America/New_York")
except Exception:  # no tzdata: fixed EST offset (report hour may drift 1h in DST)
    _ET = _dt.timezone(_dt.timedelta(hours=-5))

USAGE_KINDS = ("command", "message", "button", "other")
_usage_ready = False

def et_day(ts=None):
    """America/New_York calendar day (YYYY-MM-DD) for a unix ts."""
    return _dt.datetime.fromtimestamp(int(ts if ts is not None else time.time()), _ET).strftime("%Y-%m-%d")

def _et_bounds(day):
    """(start_ts, end_ts) unix bounds of one America/New_York day."""
    d = _dt.datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=_ET)
    return int(d.timestamp()), int((d + _dt.timedelta(days=1)).timestamp())

def _ensure_usage_tables(c):
    c.execute("""CREATE TABLE IF NOT EXISTS usage_chats(
        chat_id INTEGER PRIMARY KEY, chat_type TEXT,
        first_seen_ts INTEGER, last_seen_ts INTEGER,
        is_member INTEGER, seeded INTEGER DEFAULT 0)""")
    c.execute("""CREATE TABLE IF NOT EXISTS usage_users(
        user_id INTEGER PRIMARY KEY,
        first_seen_ts INTEGER, last_seen_ts INTEGER,
        first_seen_dm_ts INTEGER, last_seen_dm_ts INTEGER,
        first_seen_group_ts INTEGER, last_seen_group_ts INTEGER,
        seeded INTEGER DEFAULT 0)""")
    c.execute("""CREATE TABLE IF NOT EXISTS usage_sightings(
        chat_id INTEGER, user_id INTEGER, day TEXT,
        PRIMARY KEY(chat_id, user_id, day))""")
    c.execute("""CREATE TABLE IF NOT EXISTS usage_chat_days(
        chat_id INTEGER, day TEXT, PRIMARY KEY(chat_id, day))""")
    c.execute("""CREATE TABLE IF NOT EXISTS usage_user_days(
        user_id INTEGER, day TEXT, PRIMARY KEY(user_id, day))""")
    c.execute("""CREATE TABLE IF NOT EXISTS usage_interactions(
        day TEXT, kind TEXT, count INTEGER DEFAULT 0,
        PRIMARY KEY(day, kind))""")
    c.execute("""CREATE TABLE IF NOT EXISTS usage_meta(
        key TEXT PRIMARY KEY, value TEXT)""")

def _ensure_usage(c):
    global _usage_ready
    _ensure_usage_tables(c)
    if _usage_ready:
        return
    _usage_ready = True
    r = c.execute("SELECT value FROM usage_meta WHERE key='seeded'").fetchone()
    if r is None:
        _seed_usage(c)
        c.execute("INSERT INTO usage_meta(key, value) VALUES('seeded', ?)",
                  (str(int(time.time())),))
    c.commit()

def _chat_upsert(c, chat_id, chat_type, first, last, is_member, seeded):
    c.execute("""INSERT INTO usage_chats(chat_id, chat_type, first_seen_ts, last_seen_ts, is_member, seeded)
                 VALUES(?, ?, ?, ?, ?, ?)
                 ON CONFLICT(chat_id) DO UPDATE SET
                   chat_type = COALESCE(excluded.chat_type, usage_chats.chat_type),
                   first_seen_ts = MIN(usage_chats.first_seen_ts, excluded.first_seen_ts),
                   last_seen_ts = MAX(usage_chats.last_seen_ts, excluded.last_seen_ts),
                   is_member = COALESCE(excluded.is_member, usage_chats.is_member)""",
              (int(chat_id), chat_type, int(first), int(last),
               None if is_member is None else (1 if is_member else 0), int(seeded)))

def _user_upsert(c, user_id, first, last, dm=None, grp=None, seeded=0):
    dmf, dml = dm if dm else (None, None)
    grf, grl = grp if grp else (None, None)
    c.execute("""INSERT INTO usage_users(user_id, first_seen_ts, last_seen_ts,
                   first_seen_dm_ts, last_seen_dm_ts, first_seen_group_ts, last_seen_group_ts, seeded)
                 VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                 ON CONFLICT(user_id) DO UPDATE SET
                   first_seen_ts = MIN(usage_users.first_seen_ts, excluded.first_seen_ts),
                   last_seen_ts = MAX(usage_users.last_seen_ts, excluded.last_seen_ts),
                   first_seen_dm_ts = CASE
                     WHEN usage_users.first_seen_dm_ts IS NULL THEN excluded.first_seen_dm_ts
                     WHEN excluded.first_seen_dm_ts IS NULL THEN usage_users.first_seen_dm_ts
                     ELSE MIN(usage_users.first_seen_dm_ts, excluded.first_seen_dm_ts) END,
                   last_seen_dm_ts = CASE
                     WHEN usage_users.last_seen_dm_ts IS NULL THEN excluded.last_seen_dm_ts
                     WHEN excluded.last_seen_dm_ts IS NULL THEN usage_users.last_seen_dm_ts
                     ELSE MAX(usage_users.last_seen_dm_ts, excluded.last_seen_dm_ts) END,
                   first_seen_group_ts = CASE
                     WHEN usage_users.first_seen_group_ts IS NULL THEN excluded.first_seen_group_ts
                     WHEN excluded.first_seen_group_ts IS NULL THEN usage_users.first_seen_group_ts
                     ELSE MIN(usage_users.first_seen_group_ts, excluded.first_seen_group_ts) END,
                   last_seen_group_ts = CASE
                     WHEN usage_users.last_seen_group_ts IS NULL THEN excluded.last_seen_group_ts
                     WHEN excluded.last_seen_group_ts IS NULL THEN usage_users.last_seen_group_ts
                     ELSE MAX(usage_users.last_seen_group_ts, excluded.last_seen_group_ts) END""",
              (int(user_id), int(first), int(last), dmf, dml, grf, grl, int(seeded)))

def _seed_usage(c):
    """One-time conservative seed from evidence already in this DB.

    Sources (what each genuinely proves):
    - messages: the chat existed and the user spoke there at ts
      (earliest real timestamps we have; chats keep type by id sign).
    - mod_groups / members_verified (ts): chat + user were there at ts.
    - rank_override (ts): user active in that group at ts.
    - gbans / ai_bans / elevated_users (ts): the user existed by ts.
    - chat_settings / catchup / watched_validators / faq /
      pr_subscriptions / rank_days / first_msg_seen / captcha_pending /
      fresh_holds / user_lang: id-only evidence, no timestamp — seeded
      at seed time and flagged, so they never count as "new".
    Membership is NEVER seeded as known: every seeded chat starts
    is_member=NULL (unknown) and only a live update confirms it.
    """
    now = int(time.time())
    chats, users = {}, {}

    def see_chat(cid, first=None, last=None):
        if cid is None: return
        cid = int(cid)
        e = chats.setdefault(cid, {"first": None, "last": None})
        if first is not None: e["first"] = first if e["first"] is None else min(e["first"], first)
        if last is not None: e["last"] = last if e["last"] is None else max(e["last"], last)

    def see_user(uid, first=None, last=None, dm=None, grp=None):
        if uid is None: return
        uid = int(uid)
        e = users.setdefault(uid, {"first": None, "last": None, "dmf": None, "dml": None, "grf": None, "grl": None})
        if first is not None: e["first"] = first if e["first"] is None else min(e["first"], first)
        if last is not None: e["last"] = last if e["last"] is None else max(e["last"], last)
        if dm is not None:
            e["dmf"] = dm[0] if e["dmf"] is None else min(e["dmf"], dm[0])
            e["dml"] = dm[1] if e["dml"] is None else max(e["dml"], dm[1])
        if grp is not None:
            e["grf"] = grp[0] if e["grf"] is None else min(e["grf"], grp[0])
            e["grl"] = grp[1] if e["grl"] is None else max(e["grl"], grp[1])

    for r in c.execute("SELECT chat_id, MIN(ts) f, MAX(ts) l FROM messages GROUP BY chat_id"):
        see_chat(r["chat_id"], r["f"], r["l"])
    for r in c.execute("""SELECT user_id, chat_id, MIN(ts) f, MAX(ts) l FROM messages
                          WHERE user_id IS NOT NULL GROUP BY user_id, chat_id"""):
        if r["chat_id"] and r["chat_id"] > 0:
            see_user(r["user_id"], r["f"], r["l"], dm=(r["f"], r["l"]))
        else:
            see_user(r["user_id"], r["f"], r["l"], grp=(r["f"], r["l"]))
    for r in c.execute("SELECT chat_id, ts FROM mod_groups"):
        see_chat(r["chat_id"], r["ts"], r["ts"])
    for r in c.execute("SELECT chat_id, user_id, ts FROM members_verified"):
        see_chat(r["chat_id"], r["ts"], r["ts"]); see_user(r["user_id"], r["ts"], r["ts"], grp=(r["ts"], r["ts"]))
    for r in c.execute("SELECT chat_id, user_id, ts FROM rank_override"):
        see_chat(r["chat_id"], r["ts"], r["ts"]); see_user(r["user_id"], r["ts"], r["ts"], grp=(r["ts"], r["ts"]))
    for tbl in ("gbans", "ai_bans", "elevated_users"):
        for r in c.execute(f"SELECT user_id, ts FROM {tbl}"):
            see_user(r["user_id"], r["ts"], r["ts"])
    for r in c.execute("SELECT DISTINCT chat_id FROM chat_settings"):
        see_chat(r["chat_id"], now, now)
    for r in c.execute("SELECT chat_id, user_id FROM catchup"):
        see_chat(r["chat_id"], now, now)
        if r["chat_id"] and r["chat_id"] > 0: see_user(r["user_id"], now, now, dm=(now, now))
        else: see_user(r["user_id"], now, now, grp=(now, now))
    for r in c.execute("SELECT chat_id, user_id FROM rank_days"):
        see_chat(r["chat_id"], now, now); see_user(r["user_id"], now, now, grp=(now, now))
    for tbl in ("first_msg_seen", "captcha_pending", "fresh_holds"):
        for r in c.execute(f"SELECT chat_id, user_id FROM {tbl}"):
            see_chat(r["chat_id"], now, now); see_user(r["user_id"], now, now, grp=(now, now))
    for r in c.execute("SELECT user_id FROM user_lang"):
        see_user(r["user_id"], now, now)
    _ensure_val_table(c)
    for r in c.execute("SELECT DISTINCT chat_id FROM watched_validators"):
        see_chat(r["chat_id"], now, now)
    for r in c.execute("SELECT DISTINCT chat_id FROM faq"):
        see_chat(r["chat_id"], now, now)
    _ensure_pr_tables(c)
    for r in c.execute("SELECT DISTINCT chat_id FROM pr_subscriptions"):
        see_chat(r["chat_id"], now, now)

    for cid, e in chats.items():
        _chat_upsert(c, cid, "group" if cid < 0 else "private",
                     e["first"] or now, e["last"] or now, None, seeded=1)
    for uid, e in users.items():
        _user_upsert(c, uid, e["first"] or now, e["last"] or now,
                     dm=(e["dmf"], e["dml"]) if e["dmf"] is not None else None,
                     grp=(e["grf"], e["grl"]) if e["grf"] is not None else None,
                     seeded=1)

def note_membership(chat_id, is_member, chat_type=None, ts=None):
    """Record a bot-membership change (from my_chat_member updates)."""
    ts = int(ts if ts is not None else time.time())
    c = _conn()
    _chat_upsert(c, chat_id, chat_type, ts, ts, is_member, seeded=0)
    c.commit(); c.close()

def observe_update(chat_id=None, chat_type=None, user_id=None, user_is_bot=False,
                   kind=None, is_member=None, record_user=True, ts=None):
    """One passive sighting from a live update. Metadata only.

    A live group/channel update proves the bot is currently a member
    (is_member set True unless an explicit membership value is given);
    private chats carry no membership state. Bot accounts are never
    counted as people. record_user=False is for pure service events
    (e.g. someone joining a group): the chat stirred, but the person
    did not use the bot, so no user sighting is recorded.
    """
    ts = int(ts if ts is not None else time.time())
    day = et_day(ts)
    c = _conn()
    if chat_id is not None:
        member = is_member
        if member is None and chat_type in ("group", "supergroup", "channel"):
            member = True
        _chat_upsert(c, chat_id, chat_type, ts, ts, member, seeded=0)
        if int(chat_id) < 0:
            c.execute("INSERT OR IGNORE INTO usage_chat_days(chat_id, day) VALUES(?, ?)", (int(chat_id), day))
    if user_id is not None and not user_is_bot and record_user:
        dm = (ts, ts) if chat_type == "private" else None
        grp = (ts, ts) if chat_type in ("group", "supergroup", "channel") else None
        _user_upsert(c, user_id, ts, ts, dm=dm, grp=grp, seeded=0)
        c.execute("INSERT OR IGNORE INTO usage_user_days(user_id, day) VALUES(?, ?)", (int(user_id), day))
        if chat_id is not None:
            c.execute("INSERT OR IGNORE INTO usage_sightings(chat_id, user_id, day) VALUES(?, ?, ?)",
                      (int(chat_id), int(user_id), day))
    if kind in USAGE_KINDS:
        c.execute("""INSERT INTO usage_interactions(day, kind, count) VALUES(?, ?, 1)
                     ON CONFLICT(day, kind) DO UPDATE SET count = count + 1""", (day, kind))
    c.commit(); c.close()

def registry_counts(day=None):
    """Aggregate usage numbers for one America/New_York day (default today)."""
    day = day or et_day()
    start, end = _et_bounds(day)
    c = _conn()
    def q(sql, args=()):
        return c.execute(sql, args).fetchone()[0]
    inter = {k: 0 for k in USAGE_KINDS}
    for r in c.execute("SELECT kind, count FROM usage_interactions WHERE day=?", (day,)):
        inter[r["kind"]] = r["count"]
    out = {
        "day": day,
        "groups_member": q("SELECT COUNT(*) FROM usage_chats WHERE chat_id < 0 AND is_member = 1"),
        "groups_unknown": q("SELECT COUNT(*) FROM usage_chats WHERE chat_id < 0 AND is_member IS NULL"),
        "groups_left": q("SELECT COUNT(*) FROM usage_chats WHERE chat_id < 0 AND is_member = 0"),
        "groups_active_today": q("SELECT COUNT(DISTINCT chat_id) FROM usage_chat_days WHERE day=?", (day,)),
        "new_groups_today": q("""SELECT COUNT(*) FROM usage_chats
                                 WHERE chat_id < 0 AND seeded = 0 AND first_seen_ts >= ? AND first_seen_ts < ?""",
                              (start, end)),
        "people_total": q("SELECT COUNT(*) FROM usage_users"),
        "people_dm_total": q("SELECT COUNT(*) FROM usage_users WHERE first_seen_dm_ts IS NOT NULL"),
        "people_group_total": q("SELECT COUNT(*) FROM usage_users WHERE first_seen_group_ts IS NOT NULL"),
        "people_active_today": q("SELECT COUNT(DISTINCT user_id) FROM usage_user_days WHERE day=?", (day,)),
        "dm_active_today": q("SELECT COUNT(DISTINCT user_id) FROM usage_sightings WHERE day=? AND chat_id > 0", (day,)),
        "new_people_today": q("""SELECT COUNT(*) FROM usage_users
                                 WHERE seeded = 0 AND first_seen_ts >= ? AND first_seen_ts < ?""",
                              (start, end)),
        "interactions_today": inter,
        "interactions_total": sum(inter.values()),
        "messages_logged": q("SELECT COUNT(*) FROM messages"),
    }
    c.close()
    return out

# --- Wallet Security (2026-10-29): per-user personal wallet watches ---
# Rows are keyed by user_id: a watch is visible ONLY to its owner.
# Alerts are DM'd to that user_id and nowhere else. All queries are
# parameterized; addresses reach this layer only after strict bech32
# validation in walletwatch.py. Snapshots are the bot's own JSON of
# public on-chain state (balances/stakes/NFT ids) — no secrets, no
# keys, nothing a block explorer doesn't already show.
WALLET_WATCH_GLOBAL_CAP = int(os.getenv("WALLET_WATCH_GLOBAL_CAP", "500"))

def _ensure_wallet_watch(c):
    c.execute("""CREATE TABLE IF NOT EXISTS wallet_watches(
        user_id INTEGER, address TEXT, active INTEGER DEFAULT 1,
        snapshot TEXT DEFAULT '', last_checked INTEGER DEFAULT 0,
        PRIMARY KEY(user_id, address))""")
    c.execute("""CREATE TABLE IF NOT EXISTS watch_contracts(
        user_id INTEGER, contract TEXT, kind TEXT,
        PRIMARY KEY(user_id, contract))""")
    c.execute("""CREATE TABLE IF NOT EXISTS watch_alert_log(
        user_id INTEGER, address TEXT, alert_hash TEXT, ts INTEGER,
        PRIMARY KEY(user_id, address, alert_hash))""")

def wallet_watch_add(user_id, address, snapshot_json):
    """Returns 'added' | 'exists' | 'user_cap' | 'global_cap'."""
    import walletwatch
    c = _conn(); _ensure_wallet_watch(c)
    row = c.execute("SELECT address FROM wallet_watches WHERE user_id=? AND address=?", (user_id, address)).fetchone()
    if row:
        c.execute("UPDATE wallet_watches SET active=1, snapshot=? WHERE user_id=? AND address=?", (snapshot_json, user_id, address))
        c.commit(); c.close(); return "exists"
    n_user = c.execute("SELECT COUNT(*) AS n FROM wallet_watches WHERE user_id=?", (user_id,)).fetchone()["n"]
    if n_user >= walletwatch.MAX_WALLETS_PER_USER:
        c.close(); return "user_cap"
    n_all = c.execute("SELECT COUNT(*) AS n FROM wallet_watches").fetchone()["n"]
    if n_all >= WALLET_WATCH_GLOBAL_CAP:
        c.close(); return "global_cap"
    c.execute("INSERT INTO wallet_watches(user_id,address,active,snapshot,last_checked) VALUES(?,?,1,?,0)", (user_id, address, snapshot_json))
    c.commit(); c.close(); return "added"

def wallet_watch_list(user_id):
    c = _conn(); _ensure_wallet_watch(c)
    rows = c.execute("SELECT * FROM wallet_watches WHERE user_id=? ORDER BY address", (user_id,)).fetchall()
    c.close(); return [dict(r) for r in rows]

def wallet_watch_remove(user_id, address):
    c = _conn(); _ensure_wallet_watch(c)
    cur = c.execute("DELETE FROM wallet_watches WHERE user_id=? AND address=?", (user_id, address))
    c.commit(); n = cur.rowcount; c.close(); return n

def wallet_watch_set_active(user_id, active, address=None):
    c = _conn(); _ensure_wallet_watch(c)
    if address:
        cur = c.execute("UPDATE wallet_watches SET active=? WHERE user_id=? AND address=?", (1 if active else 0, user_id, address))
    else:
        cur = c.execute("UPDATE wallet_watches SET active=? WHERE user_id=?", (1 if active else 0, user_id))
    c.commit(); n = cur.rowcount; c.close(); return n

def wallet_watch_due(limit=25):
    """Active watches, least-recently-checked first — the job takes
    a slice each cycle so checks stagger instead of hammering the
    public LCD all at once."""
    c = _conn(); _ensure_wallet_watch(c)
    rows = c.execute("SELECT * FROM wallet_watches WHERE active=1 ORDER BY last_checked ASC LIMIT ?", (limit,)).fetchall()
    c.close(); return [dict(r) for r in rows]

def wallet_watch_touch(user_id, address, ts):
    c = _conn(); _ensure_wallet_watch(c)
    c.execute("UPDATE wallet_watches SET last_checked=? WHERE user_id=? AND address=?", (ts, user_id, address))
    c.commit(); c.close()

def wallet_watch_update_snapshot(user_id, address, snapshot_json, ts):
    c = _conn(); _ensure_wallet_watch(c)
    c.execute("UPDATE wallet_watches SET snapshot=?, last_checked=? WHERE user_id=? AND address=?", (snapshot_json, ts, user_id, address))
    c.commit(); c.close()

def watch_contract_add(user_id, contract, kind):
    """Returns 'added' | 'exists' | 'cap'."""
    import walletwatch
    c = _conn(); _ensure_wallet_watch(c)
    row = c.execute("SELECT contract FROM watch_contracts WHERE user_id=? AND contract=?", (user_id, contract)).fetchone()
    if row: c.close(); return "exists"
    n = c.execute("SELECT COUNT(*) AS n FROM watch_contracts WHERE user_id=?", (user_id,)).fetchone()["n"]
    if n >= walletwatch.MAX_CONTRACTS_PER_USER:
        c.close(); return "cap"
    c.execute("INSERT INTO watch_contracts(user_id,contract,kind) VALUES(?,?,?)", (user_id, contract, kind))
    c.commit(); c.close(); return "added"

def watch_contracts_for(user_id):
    c = _conn(); _ensure_wallet_watch(c)
    rows = c.execute("SELECT * FROM watch_contracts WHERE user_id=? ORDER BY contract", (user_id,)).fetchall()
    c.close(); return [dict(r) for r in rows]

def watch_contract_remove(user_id, contract):
    c = _conn(); _ensure_wallet_watch(c)
    cur = c.execute("DELETE FROM watch_contracts WHERE user_id=? AND contract=?", (user_id, contract))
    c.commit(); n = cur.rowcount; c.close(); return n

def watch_alert_seen(user_id, address, alert_hash, now, window):
    c = _conn(); _ensure_wallet_watch(c)
    r = c.execute("SELECT ts FROM watch_alert_log WHERE user_id=? AND address=? AND alert_hash=?", (user_id, address, alert_hash)).fetchone()
    c.close()
    return bool(r) and (now - r["ts"] < window)

def watch_alert_mark(user_id, address, alert_hash, ts):
    c = _conn(); _ensure_wallet_watch(c)
    c.execute("INSERT INTO watch_alert_log(user_id,address,alert_hash,ts) VALUES(?,?,?,?) ON CONFLICT(user_id,address,alert_hash) DO UPDATE SET ts=excluded.ts", (user_id, address, alert_hash, ts))
    c.execute("DELETE FROM watch_alert_log WHERE ts < ?", (ts - 7 * 86400,))
    c.commit(); c.close()

def wallet_watch_counts():
    """Counts ONLY (owner reporting) — never addresses or user ids."""
    c = _conn(); _ensure_wallet_watch(c)
    w = c.execute("SELECT COUNT(*) AS n FROM wallet_watches").fetchone()["n"]
    u = c.execute("SELECT COUNT(DISTINCT user_id) AS n FROM wallet_watches").fetchone()["n"]
    c.close(); return {"watches": w, "users": u}

def wallet_watch_active_users():
    """Distinct user ids with at least one ACTIVE watch — the
    downtime-notice fanout list. Ids only; no addresses leave the
    store in bulk."""
    c = _conn(); _ensure_wallet_watch(c)
    rows = c.execute("SELECT DISTINCT user_id FROM wallet_watches WHERE active=1").fetchall()
    c.close(); return [r["user_id"] for r in rows]
