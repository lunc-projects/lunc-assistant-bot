import os, re, collections
import httpx

import budget

AI_API_KEY = os.getenv("AI_API_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("GROQ_API_KEY") or ""
AI_BASE_URL = os.getenv("AI_BASE_URL", "https://api.openai.com/v1")
AI_MODEL = os.getenv("AI_MODEL", "gpt-4o-mini")
# Groq quick-start: set AI_BASE_URL=https://api.groq.com/openai/v1 and AI_MODEL=llama-3.1-8b-instant

# Minimized so the daily pot lasts: short answers, trimmed transcripts.
MAX_TOKENS = 500
TRANSCRIPT_CHARS = 10_000

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

async def chat(messages, temperature=0.3, lang="en") -> str | None:
    if not AI_API_KEY:
        return None
    messages = with_lang(messages, lang)
    # Daily pot: reserve the call's estimated cost first. A blocked call
    # returns None without spending anything; callers check
    # budget.exhausted() to tell the pot-empty note apart from other errors.
    # Token policy: minimized inputs (summary transcript ~10k chars) +
    # 500 output tokens, under the 200,000/day pot (budget.py) matching the
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
    return "\n".join(lines)

SUMMARY_SYSTEM = """You are LUNC Assistant Bot. Summarize Telegram group messages into a quick, scannable summary.
Format exactly:
⚡ TL;DR (3 lines max)
📌 Key Topics (bullets, who raised what matters)
✅ Decisions Made (or 'None clear')
❓ Unanswered Questions
🔗 Links / Contracts / Proposals Mentioned (deduped, or 'None')
📋 Action Items (with @name if named, or 'None')
Be accurate, do not invent messages, contracts, or decisions not in the log. Keep it tight: short bullets, no filler, whole summary well under 500 tokens."""

async def summarize(rows, detailed=False, kb_text="", lang="en") -> str:
    if not rows:
        return "No messages logged yet. I can only summarize messages sent after I joined this group."
    transcript = "\n".join(f"[{r['ts']}] {r['user_name']}: {r['text']}" for r in rows if r["text"])
    # Keep within sane prompt size: last ~10k chars (minimized so the daily
    # pot lasts — summaries are the biggest input cost, and 10k chars still
    # covers a busy group)
    transcript = transcript[-TRANSCRIPT_CHARS:]
    out = await chat([
        {"role": "system", "content": SUMMARY_SYSTEM + ("\nGive more detail per topic." if detailed else "")},
        {"role": "user", "content": f"Summarize these {len(rows)} messages:\n\n{transcript}"},
    ], lang=lang)
    if out is None and budget.exhausted():
        # Pot empty: the bot still works — basic summary plus the note.
        return extractive_summary(rows, detailed) + "\n\n" + DAILY_LIMIT_NOTE
    return out or extractive_summary(rows, detailed)
