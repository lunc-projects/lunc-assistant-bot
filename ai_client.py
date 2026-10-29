import os, re, collections
import httpx

import budget

AI_API_KEY = os.getenv("AI_API_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("GROQ_API_KEY") or ""
AI_BASE_URL = os.getenv("AI_BASE_URL", "https://api.openai.com/v1")
AI_MODEL = os.getenv("AI_MODEL", "gpt-4o-mini")
# Groq quick-start: set AI_BASE_URL=https://api.groq.com/openai/v1 and AI_MODEL=llama-3.1-8b-instant

# Minimized so the daily pot lasts: short answers, trimmed transcripts.
# 250 (cut from 500, owner decision 2026-10-27) — a code constant, NOT an
# env var: no MAX_TOKENS env read exists anywhere in the bot, so this
# value is what Railway runs unless the code changes.
MAX_TOKENS = 250
TRANSCRIPT_CHARS = 10_000

# Standing instructions appended to the system message of EVERY AI call
# (ask, mentions, summaries, tldr) — one enforcement point, so no AI path
# can skip them. Owner decisions 2026-10-27: smaller answers, text-only
# answers, and hard content rules with an explicit carve-out for
# defensive security education (a core job of this bot).
AI_RULES = (
    "Standing rules for every answer: Keep it short and plain — a few sentences, "
    "no padding, no repetition. Answer in plain text only. Do not include image "
    "or video links or media of any kind. "
    "Hard content rules: if asked for pornographic or erotic content, refuse with "
    "a short, polite refusal. If asked for hacking instructions of any kind — "
    "exploits, malware, phishing, stealing wallets or seed phrases, or ways to "
    "bypass security or access controls — refuse with a short, polite refusal. "
    "If asked for how-to instructions for any other illegal activity, refuse the "
    "same way. Teaching people to protect themselves stays allowed and welcome: "
    "how to keep a wallet and seed phrase safe, how to spot scams and phishing, "
    "and other defensive security education are fine."
)

# /ask current-events honesty rule (owner, 2026-10-29): the AI has NO
# live news wire of its own — /news (RSS headlines) is the bot's only
# current-events source. Appended to the ASK system prompts (the /ask
# command and the @mention ask path in bot.py) — NOT to AI_RULES, so
# summaries/tldr stay untouched. Trigger for it: the owner asked "What
# happened to Binance? The site is offline…" and got a long generic
# brush-off ("check their Twitter/blog/Reddit…") instead of a short,
# honest "not my wire — headlines are on /news".
CURRENT_EVENTS_RULE = (
    "Current-events rule: you have NO live news wire of your own, and your "
    "training knowledge may be out of date. If the question is about a "
    "current event — an outage, 'what happened to X', today's news, or "
    "anything else that needs today's facts — answer SHORT, in one or two "
    "sentences: say you have no live news of your own, and point to /news "
    "for the latest headlines. Do NOT pad the answer with generic advice "
    "about checking the project's Twitter, blog, status page or Reddit, and "
    "NEVER speculate about what is happening in an ongoing event."
)

def with_rules(messages):
    """Append AI_RULES to the system message (creating one if absent).
    Pure function — unit-testable without network, and never mutates the
    caller's list."""
    out = [dict(m) for m in messages]
    for m in out:
        if m.get("role") == "system":
            m["content"] = m["content"] + "\n" + AI_RULES
            return out
    out.insert(0, {"role": "system", "content": AI_RULES})
    return out

DAILY_LIMIT_NOTE = ("⏳ Daily limit reached — be back soon! AI answers are paused "
                     "until more tokens come at midnight UTC. The bot still works "
                     "for simple commands and basic summaries.")

def with_lang(messages, lang="en"):
    """Append the reply-language instruction to the system message (if any).
    Pure function — unit-testable without network. Unknown codes fall back
    to English via lang.normalize, so a bad stored value never breaks a call."""
    import lang as lang_mod
    extra = lang_mod.instruction(lang)
    if not extra:
        return messages
    out = [dict(m) for m in messages]
    for m in out:
        if m.get("role") == "system":
            m["content"] = m["content"] + "\n" + extra
            return out
    out.insert(0, {"role": "system", "content": extra})
    return out

# Matches a Telegram handle at the start of a token: "@" NOT preceded by a
# word character (so start-of-string, whitespace, and opening punctuation
# all count, while the "@" inside an email address — preceded by a word
# character — is left alone), followed by 3+ handle characters.
_MENTION_RE = re.compile(r"(?<![A-Za-z0-9_])@([A-Za-z0-9_]{3,})")

def strip_mentions(text: str) -> str:
    """Remove the "@" from Telegram handles, leaving the bare name
    ("@steve_b" -> "steve_b"). Summary-family output only (owner decision
    2026-10-28): a summary that writes @name re-tags/pings that person in
    the group, so summaries must never carry a live mention. Email
    addresses are untouched. Pure function — unit-testable."""
    if not text:
        return text
    return _MENTION_RE.sub(r"\1", text)

async def chat(messages, temperature=0.3, lang="en") -> str | None:
    if not AI_API_KEY:
        return None
    messages = with_rules(with_lang(messages, lang))
    # Daily pot: reserve the call's estimated cost first. A blocked call
    # returns None without spending anything; callers check
    # budget.exhausted() to tell the pot-empty note apart from other errors.
    # Token policy: minimized inputs (summary transcript ~10k chars) +
    # 250 output tokens, under the 200,000/day pot (budget.py) matching the
    # Groq free allowance. Data-command replies use no AI tokens at all —
    # only the AI paths call this module.
    estimate = budget.estimate_input(messages) + MAX_TOKENS
    if not budget.reserve(estimate):
        return None
    try:
        async with httpx.AsyncClient(timeout=60, proxy=os.getenv('OUTBOUND_PROXY') or None) as c:
            r = await c.post(f"{AI_BASE_URL.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {AI_API_KEY}"},
                json={"model": AI_MODEL, "messages": messages, "temperature": temperature, "max_tokens": MAX_TOKENS})
            r.raise_for_status()
            out = r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        budget.refund(estimate)
        print(f"AI error: {e}")
        return None
    # Settle: give back the unused part of the output reservation.
    budget.refund(max(0, MAX_TOKENS - len(out) // 4))
    return out

def extractive_summary(rows, detailed=False) -> str:
    """Fallback when no AI key: still useful - stats, links, active users, samples."""
    if not rows:
        return "No messages logged yet. I can only summarize messages sent after I joined this group."
    total = len(rows)
    users = collections.Counter(r["user_name"] for r in rows)
    links = []
    for r in rows:
        links += re.findall(r"https?://\S+", r["text"] or "")
    links = list(dict.fromkeys(links))[:10]
    top = ", ".join(f"{u} ({n})" for u, n in users.most_common(5))
    lines = [f"⚡ TL;DR — {total} messages logged", f"👥 Most active: {top}"]
    if links:
        lines.append("🔗 Links mentioned:\n" + "\n".join(links))
    lines.append("\n📌 Recent messages (condensed):")
    sample = rows[-25:] if not detailed else rows[-60:]
    for r in sample:
        t = (r["text"] or "")[:180].replace("\n", " ")
        if t: lines.append(f"• {r['user_name']}: {t}")
    if not AI_API_KEY:
        lines.append("\nℹ️ Add AI_API_KEY in Railway for full AI summaries — this is the no-key fallback view.")
    # Summary-family output: never ship a live @mention (re-tags the person).
    return strip_mentions("\n".join(lines))

SUMMARY_SYSTEM = """You are LUNC Assistant Bot. Summarize Telegram group messages into a SHORT, scannable summary.
Hard limits: at most 5 short lines and about 450 characters total. Key points only — no intro, no outro, no padding.
Format:
⚡ TL;DR — one line.
Then up to 4 bullets (•) covering the key points: what mattered, what was decided, what is still open. Fold any links or proposals into the bullet they belong to.
Names: refer to people by plain display name only. NEVER write @usernames — an @name re-notifies that person.
Be accurate, do not invent messages, contracts, or decisions not in the log. If a point must be cut to fit, cut words per point, not a whole main topic."""

async def summarize(rows, detailed=False, kb_text="", lang="en") -> str:
    if not rows:
        return "No messages logged yet. I can only summarize messages sent after I joined this group."
    transcript = "\n".join(f"[{r['ts']}] {r['user_name']}: {r['text']}" for r in rows if r["text"])
    # Keep within sane prompt size: last ~10k chars (minimized so the daily
    # pot lasts — summaries are the biggest input cost, and 10k chars still
    # covers a busy group)
    transcript = transcript[-TRANSCRIPT_CHARS:]
    out = await chat([
        {"role": "system", "content": SUMMARY_SYSTEM + ("\nA little more detail per point is OK, but stay under about 8 short lines." if detailed else "")},
        {"role": "user", "content": f"Summarize these {len(rows)} messages:\n\n{transcript}"},
    ], lang=lang)
    if out is None and budget.exhausted():
        # Pot empty: the bot still works — basic summary plus the note.
        return extractive_summary(rows, detailed) + "\n\n" + DAILY_LIMIT_NOTE
    if out:
        # The deterministic guarantee behind the prompt rule: no summary
        # leaves with a live @mention, whatever the model wrote.
        return strip_mentions(out)
    return extractive_summary(rows, detailed)
