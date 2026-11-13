"""Outbound anti-spam guard (2026-11-13).

Incident: the bot posted a group message that was ONLY three gibberish
bot links (@gAm0kiGk8bot / @gbrcm9dfdbot / @GIU3YH3Lbot) — either a
leaked token (revoked the same day) or the bot's own AI echoing spam
links harvested from group chatter. This module is the code-side half
of the fix: whatever path produced it, a message that is nothing but
links / @mentions can never leave the bot again.

Two pieces:

- outbound_blocked(text) — True when the text consists ONLY of URLs,
  t.me links and/or @mentions (plus punctuation/emoji). Links inside
  real sentences are fine; a message that is ALL link is not. bot.py
  enforces this at the single Bot.send_message choke point for every
  group/channel send.

- sanitize_ai_text(text) — for AI-generated output (summaries, /ask,
  group-AI replies, translate-rescue): drops lines that are bare
  link/mention lists, returns "" when nothing substantive remains
  (callers then send nothing and log instead).

Pure stdlib, no imports from the bot — unit-tested in test_outbound.py.
"""
import re

_MENTION = re.compile(r"^@[A-Za-z0-9_]{3,}$")
_URL = re.compile(r"^(?:https?://|tg://|www\.)\S+$", re.IGNORECASE)
_MD_LINK = re.compile(r"^\[[^\]]*\]\(\S+\)$")
_BARE_DOMAIN = re.compile(
    r"^(?:[A-Za-z0-9-]+\.)+(?:com|net|org|io|me|xyz|app|dev|co|info|site|"
    r"online|club|fun|live|gg|money|finance)(?:/\S*)?$",
    re.IGNORECASE,
)
# Decoration stripped from token edges before classifying: markdown,
# bullets, brackets, quotes, sentence punctuation.
_EDGE = " \t\r\n•·–—-*_`~|<>\"'«»()[]{}.,;:!?"
_ALNUM = re.compile(r"[A-Za-z0-9]")


def _is_linkish(token):
    """One whitespace-separated token that is just a link or a mention."""
    if _MD_LINK.match(token):
        return True
    t = token.strip(_EDGE)
    if not t:
        return False
    return bool(
        _MENTION.match(t) or _URL.match(t) or _BARE_DOMAIN.match(t)
    )


def _counts(text):
    """(linkish, substantive) token counts for a text."""
    linkish = substantive = 0
    for tok in str(text).split():
        if _is_linkish(tok):
            linkish += 1
        elif _ALNUM.search(tok.strip(_EDGE)):
            substantive += 1
        # punctuation/emoji-only tokens count as neither
    return linkish, substantive


def outbound_blocked(text):
    """True when a message is ONLY links / @mentions — the spam shape.

    Requires at least one linkish token and zero substantive words, so
    labelled alerts and normal sentences carrying a link always pass.
    """
    if not text or not str(text).strip():
        return False
    linkish, substantive = _counts(text)
    return linkish >= 1 and substantive == 0


def sanitize_ai_text(text):
    """Drop bare link/mention-list lines from AI-generated text.

    Returns the cleaned text, or "" when nothing substantive remains.
    Normal lines — including sentences that contain a link or a
    mention — are kept verbatim.
    """
    if not text:
        return ""
    kept = [ln for ln in str(text).splitlines()
            if not (ln.strip() and outbound_blocked(ln))]
    out = re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()
    # A remainder with no substantive word at all is not a message.
    if out and _counts(out)[1] == 0:
        return ""
    return out


def is_group_chat_id(chat_id):
    """Telegram group/supergroup/channel ids are negative ints; user
    (DM) ids are positive. The guard applies to group posts only."""
    return isinstance(chat_id, int) and chat_id < 0
