"""Pure security helpers for the LUNC Assistant Bot (2026-10-25) —
no Telegram, no database, so every rule here is unit-testable:

- Link allowlist for the first-message rule: links to official /
  community-verified domains don't get a new member kicked.
- Message fingerprints for cross-group repeat detection: the same
  long message landing in several protected groups within minutes
  is the classic scam-broadcast pattern.
- Fresh-looking account test for the post-gate hold: no username
  AND no profile photo. (Telegram exposes no account-age field;
  this is the honest proxy, and the consequence is mild — 24h
  text-only — so a false positive costs a real user little.)
"""

import hashlib
import re

# Domains a first message may link without the sender being removed.
# Kept tight on purpose: the chain's own explorer, the community
# references the owner vouches for, and the official wallet / hardware
# sites. Subdomains count (docs.cosmosrescue.com via cosmosrescue.com).
ALLOWLIST_DOMAINS = (
    "finder.terraclassic.community",
    "terraclassic.community",
    "luncscan.com",
    "validator.info",
    "statsbin.com",
    "station.money",
    "keplr.app",
    "ledger.com",
    "cosmosrescue.com",
)

_EXPLICIT_RE = re.compile(r"(?:https?://|www\.)([^\s/?#]+)", re.I)
_TME_RE = re.compile(r"(?:^|[\s(])t\.me/", re.I)
_BARE_RE = re.compile(
    r"(?<![\w/.@-])((?:[a-z0-9-]+\.)+(?:com|net|org|io|co|me|app|money|"
    r"community|info|network|xyz|site|online|finance|gg|dev|club|pro|top|vip))\b",
    re.I)


def extract_hosts(text):
    """All link hosts in a message, lowercased, www. stripped."""
    hosts = []
    for m in _EXPLICIT_RE.finditer(text or ""):
        h = m.group(1).lower().strip(".,;:!?)\"'")
        if h.startswith("www."):
            h = h[4:]
        h = h.split(":")[0]
        if h:
            hosts.append(h)
    if _TME_RE.search(text or ""):
        hosts.append("t.me")
    for m in _BARE_RE.finditer(text or ""):
        h = m.group(1).lower()
        if h not in hosts:
            hosts.append(h)
    return hosts


def _allowlisted(host):
    return any(host == d or host.endswith("." + d) for d in ALLOWLIST_DOMAINS)


def all_links_allowlisted(text):
    """True only when the message HAS links and every one is allowlisted.
    No links at all returns False (nothing to excuse)."""
    hosts = extract_hosts(text)
    if not hosts:
        return False
    return all(_allowlisted(h) for h in hosts)


_URL_STRIP_RE = re.compile(r"(https?://|www\.)\S+", re.I)
_WS_RE = re.compile(r"\s+")


def fingerprint(text, min_len=40):
    """Stable hash of a long message with URLs stripped, so a scam
    re-posted with a swapped link still matches. Short messages
    return None — they're conversation, not broadcasts."""
    norm = _URL_STRIP_RE.sub("", (text or "").lower())
    norm = _WS_RE.sub(" ", norm).strip()
    if len(norm) < min_len:
        return None
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def fresh_looking(has_username, photo_count):
    """Brand-new-looking account: no username and zero profile photos.
    photo_count=None means 'couldn't check' — never hold on a guess."""
    if photo_count is None:
        return False
    return (not has_username) and photo_count == 0
