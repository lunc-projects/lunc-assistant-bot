"""Group auto-translate (2026-11-11, Tom's request, modeled on the
Translator bot in the Token Founders group): in group chats, a message
that is clearly NOT English gets a reply-quote with its English
translation — translation only, no preamble.

v2 — QUALITY UPGRADE (2026-11-11, Tom: "We want a good translator"
after the third-party bot in the Founders group got complained about
in-chat: "Çeviri çok hata yapıyor" = "The translation makes many
mistakes"). v1 ran on Google Translate's free gtx endpoint — the same
engine family as that bot. v2 wires in the bot's own AI as a second
engine, with a strict translation-only prompt: natural fluent
English, preserve emoji/names/@mentions/numbers, output ONLY the
translation; if the text is already English the model answers with
the [[ENGLISH]] sentinel.

ENGINE ORDER — READ BEFORE FLIPPING: the AI is currently the
FALLBACK, not the primary. It is tried when gtx fails outright and
when gtx echoes the original back untranslated (a misdetection the
AI usually gets right). The planned Groq-vs-gtx quality proof could
NOT be run before shipping: on 2026-11-11 the sandbox's egress IPs
were rate-limited by Google (HTTP 429 on every gtx call after v1's
early test succeeded), and the Groq key exists only in the bot's
Railway env — by design it is never stored on this machine, so the
AI side cannot be called from here either. House rule (never fake
anything; do not ship an unverified engine as primary): gtx stays
primary until the side-by-side proof is actually run — the five
sentences are in the v2 task report; it can be run from anywhere
with the key, or from here once the 429 clears. Flipping the order
afterwards is a small, contained change in translate() only.
Everything the proof would gate on is already built and tested:
the prompt, the sentinel, the sub-budget, the settle/refund
accounting, and the use_ai switch.

POT SAFETY (hard rules):
  - AI translation calls draw from the SAME daily pot as chat AI
    (ai_client reserves/settles there), PLUS a translation-only
    sub-budget: TRANSLATE_DAILY_TOKEN_CAP = 25,000 estimated tokens
    per UTC day (~12% of the 200k pot). When the sub-budget is spent
    the AI simply stops being tried — the gtx primary is untouched,
    so translation never goes silent because of the budget and the
    chat AI's share is never eaten. Accounting is estimates in
    budget.py's own style (reserve max, settle to actual, refund
    failures in full), in-memory like budget.py: a redeploy resets
    the counter, which is fine — the caps are graceful-degrade
    guards, not billing meters.
  - ai_client.chat caps output at 250 tokens, so the AI is never
    tried on messages longer than AI_MAX_CHARS (gtx has no such cap)
    rather than risk a truncated "translation".

Spam discipline (unchanged from v1 — this bot has had a noise problem
before; guards are strict and every failure is silent: no chat
errors, no owner DM, log only):
  - English is skipped (AI sentinel, or gtx-detected "en"), as is any
    result that just echoes the original text.
  - Messages under 12 chars or under 3 letter-bearing words skipped.
  - Commands (/...) skipped.
  - Messages that are mostly links / wallet addresses / numbers /
    emoji are skipped (checked on what's left after stripping URLs
    and address-like tokens).
  - Edited messages never reach this module (separate handler).
  - Bots' messages and channel posts are skipped by the caller.
  - Per-user cooldown 30s; per-chat cap 20 translations/hour, then
    quiet until the window slides past.
  - Repeated strings are served from an in-memory cache (no engine
    call, whichever engine produced them).
"""
import datetime, re, time
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

# --- AI primary engine ---
ENGLISH_SENTINEL = "[[ENGLISH]]"
TRANSLATE_SYSTEM = (
    "You are a translation engine. Translate the user's message into "
    "natural, fluent English. Output ONLY the translation — no quotes, "
    "no preamble, no notes, no explanations. Preserve emojis, names, "
    "@mentions, numbers, links and line breaks exactly as in the "
    "original. Keep the tone: casual stays casual, slang stays slang. "
    "Translate the whole message, including any parts already in other "
    f"languages. If the message is already entirely in English, reply "
    f"with exactly {ENGLISH_SENTINEL} and nothing else."
)
# Messages longer than this go straight to Google: ai_client.chat
# caps output at 250 tokens (~900+ chars of English), and a cut-off
# translation is worse than a complete gtx one.
AI_MAX_CHARS = 800
AI_MAX_OUTPUT_TOKENS = 250  # mirrors ai_client.MAX_TOKENS
# Extra prompt chars riding along in every ai_client.chat call
# (ai_client.AI_RULES is appended to the system message there).
AI_RULES_CHARS = 900
TRANSLATE_DAILY_TOKEN_CAP = 25_000

# A refusal from the AI path (its standing content rules can decline
# to "answer") is NOT a translation — treat it as an engine failure
# and fall back to Google instead of posting it.
_REFUSAL_RE = re.compile(
    r"^(I['’]m sorry|I am sorry|Sorry,|I can['’]t|I cannot|I won['’]t|"
    r"As an AI|I understand,? but)", re.IGNORECASE)

_URL_RE = re.compile(r"(https?://|www\.|t\.me/)\S+", re.IGNORECASE)
_ADDR_RE = re.compile(
    r"\b(terra1[0-9a-z]{20,}|0x[0-9a-fA-F]{20,}|[13][a-km-zA-HJ-NP-Z1-9]{25,34}|bc1[0-9a-z]{20,})\b")


def skip_reason(text):
    """None if the text is worth sending to the translator, else a short
    reason string (for tests/logs). Pure — no I/O, no language guess:
    'is it English?' is the engines' call, made in translate()."""
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


def parse_ai_output(raw):
    """Classify a raw AI reply: ("english", None) for the sentinel,
    ("ok", translation) for a usable translation, None for failure
    (empty, or a refusal that must fall back to Google)."""
    if not raw:
        return None
    out = raw.strip()
    if not out:
        return None
    if out == ENGLISH_SENTINEL or (
            ENGLISH_SENTINEL in out and len(out) <= len(ENGLISH_SENTINEL) + 4):
        return ("english", None)
    if _REFUSAL_RE.match(out):
        return None
    return ("ok", out)


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


async def _default_ai_getter(text):
    """Translate via the bot's own AI (ai_client.chat — the existing
    Groq plumbing: key/base/model from env, main-pot accounting,
    AI_RULES enforcement). Returns the model's raw reply, or None on
    any failure (no key configured, pot empty, network/Groq error —
    ai_client.chat already returns None for all of those)."""
    import ai_client
    return await ai_client.chat([
        {"role": "system", "content": TRANSLATE_SYSTEM},
        {"role": "user", "content": text},
    ], temperature=0.1)


class Translator:
    """Stateful gate: per-user cooldown, per-chat hourly cap, cache,
    and the translation token sub-budget for the AI engine.
    `now` is injectable for tests; `getter` is an async callable
    text -> parsed gtx JSON (or None / raises on failure);
    `ai_getter` is an async callable text -> raw AI reply (or None /
    raises on failure)."""

    def __init__(self, getter=None, ai_getter=None, cooldown=USER_COOLDOWN_S,
                 hourly_cap=CHAT_HOURLY_CAP, cache_max=CACHE_MAX,
                 ai_daily_cap=TRANSLATE_DAILY_TOKEN_CAP, use_ai=True):
        self._getter = getter or _default_getter
        self._ai_getter = ai_getter or _default_ai_getter
        # bot.py wires this to its AI_ENABLED switch: with AI off,
        # translation is Google-only (exactly v1) and no budget moves.
        self.use_ai = use_ai
        self.cooldown = cooldown
        self.hourly_cap = hourly_cap
        self.cache_max = cache_max
        self.ai_daily_cap = ai_daily_cap
        self._cache = OrderedDict()      # normalized text -> translation
        self._last_user = {}             # (chat_id, user_id) -> ts
        self._chat_times = {}            # chat_id -> [ts, ...] sliding hour
        self._ai_day = None              # UTC date of the sub-budget window
        self._ai_spent = 0               # estimated AI tokens spent today

    @staticmethod
    def _key(text):
        return " ".join(text.lower().split())

    # --- spam gates (unchanged from v1) ---
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

    # --- AI sub-budget (budget.py-style estimates, UTC day window) ---
    @staticmethod
    def _ai_estimate(text):
        """Estimated tokens for one AI translation: prompt + message
        in, max output reserved — settled to actual after the call."""
        return (len(TRANSLATE_SYSTEM) + AI_RULES_CHARS + len(text)) // 4 \
            + AI_MAX_OUTPUT_TOKENS

    def _ai_rollover(self, now):
        day = datetime.datetime.fromtimestamp(
            now, tz=datetime.timezone.utc).date()
        if self._ai_day != day:
            self._ai_day = day
            self._ai_spent = 0

    def ai_spent(self, now=None):
        """Estimated AI tokens spent on translation today (tests/ops)."""
        self._ai_rollover(time.time() if now is None else now)
        return self._ai_spent

    def _ai_reserve(self, est, now):
        self._ai_rollover(now)
        if self._ai_spent + est > self.ai_daily_cap:
            return False
        self._ai_spent += est
        return True

    def _ai_settle(self, est, raw_out):
        """Refund the unused part of the output reservation; a failed
        call (raw_out None) is refunded in full — no tokens were
        spent, so the budget does not pay for it (budget.py's rule)."""
        if raw_out is None:
            self._ai_spent = max(0, self._ai_spent - est)
        else:
            actual_out = min(AI_MAX_OUTPUT_TOKENS, len(raw_out) // 4 + 1)
            self._ai_spent = max(0, self._ai_spent - (AI_MAX_OUTPUT_TOKENS - actual_out))

    async def _via_ai(self, text, now):
        """("english", None) | ("ok", translation) | None (failure,
        AI off, over-long, or sub-budget spent). Never raises."""
        if not self.use_ai:
            return None
        if len(text) > AI_MAX_CHARS:
            return None  # output-cap risk: Google handles long text
        est = self._ai_estimate(text)
        if not self._ai_reserve(est, now):
            print("[translate] AI sub-budget spent for today — AI not tried")
            return None
        try:
            raw = await self._ai_getter(text)
        except Exception as e:
            print(f"[translate] AI engine error (silent): "
                  f"{type(e).__name__}: {e}")
            raw = None
        self._ai_settle(est, raw)
        parsed = parse_ai_output(raw)
        if parsed is None and raw:
            print("[translate] AI reply unusable (silent)")
        return parsed

    async def _via_google(self, text):
        """("english", None) when gtx detects English, ("ok",
        translation) on success, None on failure. Never raises."""
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
        if lang == "en":
            return ("english", None)
        translated = translated.strip()
        return ("ok", translated) if translated else None

    async def translate(self, text, chat_id, user_id, now=None):
        """English translation to post as a reply, or None to stay
        silent. Google (gtx) primary; the bot's AI is tried when gtx
        fails or echoes the original untranslated. Never raises:
        engine and network failures are logged and swallowed (no
        chat spam, no owner alert for translate)."""
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
        translated = None
        g = await self._via_google(text)
        if g is not None:
            if g[0] == "english":
                return None  # already English — stay silent
            if g[1].lower() != text.strip().lower():
                translated = g[1]
            # else: gtx echoed the original (misdetection) — the AI
            # gets its chance before we give up.
        if translated is None:
            ai = await self._via_ai(text, now)
            if ai is not None:
                if ai[0] == "english":
                    return None  # AI says it's already English
                translated = ai[1]
        if not translated or translated.lower() == text.strip().lower():
            return None  # echo — misdetected English or untranslatable
        self._record(chat_id, user_id, now)
        self._cache[key] = translated
        self._cache.move_to_end(key)
        while len(self._cache) > self.cache_max:
            self._cache.popitem(last=False)
        return translated
