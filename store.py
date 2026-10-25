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
