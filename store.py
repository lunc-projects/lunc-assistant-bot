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
    c.execute("INSERT INTO messages(chat_id,user_id,user_name,text,ts,message_id) VALUES(?,?,?,?,?,?)",
              (chat_id, user_id, user_name, text, int(time.time()), message_id))
    c.execute("DELETE FROM messages WHERE ts < ?", (int(time.time()) - RETENTION_DAYS*86400,))
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
