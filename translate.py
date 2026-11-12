"""Group auto-translate (2026-11-11, Tom's request, modeled on the
Translator bot in the Token Founders group): in group chats, a message
that is clearly NOT English gets a reply-quote with its English
translation — translation only, no preamble.

Engine: Google Translate's free no-key endpoint
(translate.googleapis.com/translate_a/single, client=gtx) with source
language auto-detected from the same response. Verified live from the
sandbox 2026-11-11: "Klavye ayarlarını değiştirebilirsin" -> "You can
change keyboard settings." (detected "tr"). This deliberately does NOT
spend the Groq daily pot — the pot is for AI answers, not routine
translation. Repeated strings are cached in memory.

Spam discipline (this bot has had a noise problem before — guards are
strict and every failure is silent: no chat errors, no owner DM, log
only):
  - English (engine-detected "en") is skipped, as is any result that
    just echoes the original text.
  - Messages under 12 chars or under 3 letter-bearing words skipped.
  - Commands (/...) skipped (they never reach the message handler
    anyway; the guard is here so the rule holds wherever this runs).
  - Messages that are mostly links / wallet addresses / numbers /
    emoji are skipped (checked on what's left after stripping URLs
    and address-like tokens).
  - Edited messages never reach this module (separate handler).
  - Bots' messages and channel posts are skipped by the caller.
  - Per-user cooldown 30s; per-chat cap 20 translations/hour, then
    quiet until the window slides past.
"""
import re, time
from collections import OrderedDict

GTX_URL = "https://translate.googleapis.com/translate_a/single"

MIN_CHARS = 12
MIN_WORDS = 3
USER_COOLDOWN_S = 30
CHAT_HOURLY_CAP = 20
CACHE_MAX = 500
# Letter share of the non-space text after URLs/addresses are stripped:
# below this the message is mostly numbers/emoji/symbols, not language.
MIN_LETTER_RATIO = 0.4

_URL_RE = re.compile(r"(https?://|www\.|t\.me/)\S+", re.IGNORECASE)
_ADDR_RE = re.compile(
    r"\b(terra1[0-9a-z]{20,}|0x[0-9a-fA-F]{20,}|[13][a-km-zA-HJ-NP-Z1-9]{25,34}|bc1[0-9a-z]{20,})\b")


def skip_reason(text):
    """None if the text is worth sending to the translator, else a short
    reason string (for tests/logs). Pure — no I/O, no language guess:
    'is it English?' is the engine's call, made in translate()."""
    if not text:
        return "empty"
    t = text.strip()
    if t.startswith("/"):
        return "command"
    if len(t) < MIN_CHARS:
        return "too short"
    core = _ADDR_RE.sub(" ", _URL_RE.sub(" ", t))
    words = [w for w in core.split() if any(ch.isalpha() for ch in w)]
    if len(words) < MIN_WORDS:
        return "too few words"
    nonspace = [ch for ch in core if not ch.isspace()]
    if not nonspace:
        return "nothing but links/addresses"
    letters = sum(1 for ch in nonspace if ch.isalpha())
    if letters / len(nonspace) < MIN_LETTER_RATIO:
        return "mostly numbers/emoji/symbols"
    return None


def parse_gtx(data):
    """(translated, detected_lang) from a gtx response, or None.
    data[0] is a list of [translated_segment, source_segment, ...];
    data[2] is the detected source language."""
    try:
        segments = data[0]
        translated = "".join(seg[0] for seg in segments if seg and seg[0])
        lang = data[2]
    except Exception:
        return None
    if not translated or not lang:
        return None
    return translated, lang


async def _default_getter(text):
    """POST to the free gtx endpoint; returns parsed JSON or None.
    httpx is imported lazily so unit tests can import this module and
    inject a fake getter without the dependency installed."""
    import httpx
    async with httpx.AsyncClient(timeout=8) as client:
        r = await client.post(GTX_URL,
                              params={"client": "gtx", "sl": "auto", "tl": "en", "dt": "t"},
                              data={"q": text})
        r.raise_for_status()
        return r.json()


class Translator:
    """Stateful gate: per-user cooldown, per-chat hourly cap, cache.
    `now` is injectable for tests; `getter` is an async callable
    text -> parsed gtx JSON (or None / raises on failure)."""

    def __init__(self, getter=None, cooldown=USER_COOLDOWN_S,
                 hourly_cap=CHAT_HOURLY_CAP, cache_max=CACHE_MAX):
        self._getter = getter or _default_getter
        self.cooldown = cooldown
        self.hourly_cap = hourly_cap
        self.cache_max = cache_max
        self._cache = OrderedDict()      # normalized text -> translation
        self._last_user = {}             # (chat_id, user_id) -> ts
        self._chat_times = {}            # chat_id -> [ts, ...] sliding hour

    @staticmethod
    def _key(text):
        return " ".join(text.lower().split())

    def _gate(self, chat_id, user_id, now):
        last = self._last_user.get((chat_id, user_id))
        if last is not None and now - last < self.cooldown:
            return "user cooldown"
        times = [t for t in self._chat_times.get(chat_id, []) if now - t < 3600]
        self._chat_times[chat_id] = times
        if len(times) >= self.hourly_cap:
            return "chat hourly cap"
        return None

    def _record(self, chat_id, user_id, now):
        self._last_user[(chat_id, user_id)] = now
        self._chat_times.setdefault(chat_id, []).append(now)

    async def translate(self, text, chat_id, user_id, now=None):
        """English translation to post as a reply, or None to stay
        silent. Never raises: engine/network failures are logged and
        swallowed (no chat spam, no owner alert for translate)."""
        if now is None:
            now = time.time()
        if skip_reason(text):
            return None
        key = self._key(text)
        cached = self._cache.get(key)
        if cached is not None:
            # A repeat of something already translated in this chat is
            # still a translation event for the cap, but costs no call.
            if self._gate(chat_id, user_id, now):
                return None
            self._record(chat_id, user_id, now)
            return cached
        if self._gate(chat_id, user_id, now):
            return None
        try:
            data = await self._getter(text)
        except Exception as e:
            print(f"[translate] engine error (silent): {type(e).__name__}: {e}")
            return None
        parsed = parse_gtx(data) if data else None
        if not parsed:
            print("[translate] engine returned nothing usable (silent)")
            return None
        translated, lang = parsed
        translated = translated.strip()
        if lang == "en":
            return None
        if not translated or translated.lower() == text.strip().lower():
            return None  # echo — misdetected English or untranslatable
        self._record(chat_id, user_id, now)
        self._cache[key] = translated
        self._cache.move_to_end(key)
        while len(self._cache) > self.cache_max:
            self._cache.popitem(last=False)
        return translated
