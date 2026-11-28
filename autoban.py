"""Auto-ban patterns (2026-11-13) — the incident shapes, as pure text
classifiers plus a small in-memory repeat tracker.

Incident: a scammer (@YLzhangwei888) posted a USDT OTC bait ad in
"Terra Luna Classic Chat" ("prices 5%–20% above the market rate …
we will make the payment first, and then you transfer the USDT …
contact me 👉 Telegram: @YLzhangwei888"), and the bot ended up posting
a bare list of three gibberish bot links (@gAm0kiGk8bot /
@gbrcm9dfdbot / @GIU3YH3Lbot) right after it. The outbound guard
(outbound.py) stops the BOT posting that shape; this module spots the
HUMANS posting it, so bot.py can delete + ban + propagate + report.

Deliberately tight — a normal member should never trip these:

- "botlist": the message is ONLY links/mentions (outbound_blocked)
  and at least two of them are bot handles (@…bot mentions or
  t.me/<…bot> links). The incident shape.
- "scam": a payment-scam bait phrase from SCAM_PHRASES *and* a
  contact (an @mention or any link) in the same message. A phrase
  alone, or a contact alone, is not enough.
- "mule": a money-mule recruitment ad (2026-11-27). Mule-specific
  terms (代收 / 跑分) fire alone; recruiting + collect-payments
  phrasing fires together; an income claim (日入<figure> / "daily
  income <figure>") fires ONLY alongside a recruiting or collecting
  phrase — income talk alone never fires.
- "linkspam" (tracker): a second link/mention-only message from the
  same user in the same chat within WINDOW_SECONDS.

Admin/owner/self exemptions are bot.py's job (they need API calls);
everything here is pure and unit-tested in test_autoban.py.
"""
import re
import time

import outbound

WINDOW_SECONDS = 600

# Bait phrases lifted from the incident ad. Kept explicit and small on
# purpose: each is distinctive OTC-scam phrasing, and a hit ALSO needs
# a contact handle/link in the same message (see is_payment_scam).
SCAM_PHRASES = (
    "above the market rate",
    "make the payment first",
    "payment first, and then you transfer",
    "you transfer the usdt",
    "looking to buy usdt",
    "looking to sell usdt",
    "we offer the best rates",
    "most secure transaction methods",
)

REASON_LABELS = {
    "botlist": "bare bot-link list",
    "scam": "payment-scam bait with a contact handle",
    "mule": "money-mule recruitment ad",
    "linkspam": "repeated link-only posts",
    "ai-launder": "fed link spam through the bot's AI",
    "aiscam": "AI-flagged scam/spam (high confidence)",
}

_TME = re.compile(r"^(?:https?://)?(?:t\.me|telegram\.me)/([A-Za-z0-9_]{3,})/?$",
                  re.IGNORECASE)


def _tokens(text):
    out = []
    for tok in str(text or "").split():
        t = tok.strip(outbound._EDGE)
        if t:
            out.append(t)
    return out


def bot_link_count(text):
    """Tokens that are bot handles: @…bot mentions or t.me/<…bot>."""
    n = 0
    for t in _tokens(text):
        m = outbound._MENTION.match(t)
        if m and t[1:].lower().endswith("bot"):
            n += 1
            continue
        m = _TME.match(t)
        if m and m.group(1).lower().endswith("bot"):
            n += 1
    return n


def is_bare_bot_list(text):
    """Pattern (a): only links/mentions, >= 2 of them bot handles."""
    return outbound.outbound_blocked(text) and bot_link_count(text) >= 2


def is_link_only(text):
    """The message is nothing but links / @mentions."""
    return outbound.outbound_blocked(text)


def _has_contact(text):
    for t in _tokens(text):
        if (outbound._MENTION.match(t) or outbound._URL.match(t)
                or outbound._BARE_DOMAIN.match(t) or _TME.match(t)):
            return True
    return False


def is_payment_scam(text):
    """Pattern (c): scam-bait phrase AND a contact in one message."""
    low = " ".join(str(text or "").lower().split())
    if not any(p in low for p in SCAM_PHRASES):
        return False
    return _has_contact(text)


# Money-mule recruitment (2026-11-27): scammers hire people to receive
# and forward payments through their own accounts (laundering). The
# incident ad was just "招代收，日入8000" — 8 characters, far under the
# AI layer's minimum length, so this deterministic layer is its only
# home. Rules (owner ruling): the mule-specific terms fire alone;
# recruiting + collecting fires together; an income claim fires ONLY
# with a recruiting or collecting phrase — income talk alone, in
# English or Chinese, never fires. Accepted trade-off: a warning post
# quoting the raw term 代收 trips the standalone rule; admins, the
# owner and elevated users are exempt in bot.py.
MULE_TERMS = ("代收", "跑分")

RECRUIT_PHRASES_EN = (
    "seeking agents",
    "agents wanted",
    "hiring agents",
    "recruiting agents",
    "looking for agents",
    "need agents",
)
RECRUIT_PHRASES_CN = ("招代理", "招人", "招聘", "招募")

COLLECT_PHRASES_EN = (
    "collect payments",
    "collect payment",
    "receive payments",
    "receive payment",
)
COLLECT_PHRASES_CN = ("收款", "代收款")

_INCOME_CN = re.compile(r"日入\s*[¥$]?\s*\d")
_INCOME_EN = re.compile(r"daily income\D{0,20}\d")


def _has_income_claim(raw, low):
    return bool(_INCOME_CN.search(raw) or _INCOME_EN.search(low))


def is_mule_recruitment(text):
    """Pattern (d): money-mule recruitment ad."""
    raw = str(text or "")
    low = " ".join(raw.lower().split())
    if any(t in raw for t in MULE_TERMS):
        return True
    recruit = (any(p in low for p in RECRUIT_PHRASES_EN)
               or any(p in raw for p in RECRUIT_PHRASES_CN))
    collect = (any(p in low for p in COLLECT_PHRASES_EN)
               or any(p in raw for p in COLLECT_PHRASES_CN))
    if recruit and collect:
        return True
    return _has_income_claim(raw, low) and (recruit or collect)


def classify(text):
    """Single-message triggers: 'botlist' | 'scam' | 'mule' | None."""
    if is_bare_bot_list(text):
        return "botlist"
    if is_payment_scam(text):
        return "scam"
    if is_mule_recruitment(text):
        return "mule"
    return None


class LinkOnlyTracker:
    """Pattern (b): >= threshold link-only messages from one user in
    one chat inside the window. note() returns the message ids to
    delete when the threshold is hit (and resets that user), else
    None. In-memory, like the flood tracker — a redeploy just resets
    the count, which is fine for a 10-minute window."""

    def __init__(self, window=WINDOW_SECONDS, threshold=2):
        self.window = window
        self.threshold = threshold
        self._hits = {}

    def note(self, chat_id, user_id, message_id, ts=None):
        ts = int(ts if ts is not None else time.time())
        key = (chat_id, user_id)
        hits = [(t, m) for (t, m) in self._hits.get(key, [])
                if ts - t < self.window]
        hits.append((ts, message_id))
        if len(hits) >= self.threshold:
            self._hits.pop(key, None)
            return [m for (_t, m) in hits]
        self._hits[key] = hits
        return None

    def reset(self):
        self._hits.clear()


def report_url(username, user_id):
    """Where the owner's 🚩 Report button points: the offender's
    profile — t.me/<username> when they have one, else Telegram's
    tg:// user link (an allowed inline-button URL scheme)."""
    if username:
        return f"https://t.me/{username}"
    return f"tg://user?id={user_id}"


def evidence_text(user_name, username, user_id, chat_title, chat_id,
                  when_et, reason, text):
    """The owner DM body: who, where, when (ET), why, and the first
    ~120 chars of what they posted."""
    handle = f"@{username}" if username else "(no username)"
    label = REASON_LABELS.get(reason, reason)
    return (
        f"🚨 Auto-ban — {label}\n"
        f"User: {user_name} {handle} — id {user_id}\n"
        f"Group: {chat_title} ({chat_id})\n"
        f"Time: {when_et} ET\n"
        f"They posted: {str(text or '')[:120]}"
    )
