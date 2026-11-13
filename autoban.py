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
    "linkspam": "repeated link-only posts",
    "ai-launder": "fed link spam through the bot's AI",
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


def classify(text):
    """Single-message triggers: 'botlist' | 'scam' | None."""
    if is_bare_bot_list(text):
        return "botlist"
    if is_payment_scam(text):
        return "scam"
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
