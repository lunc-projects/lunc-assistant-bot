#!/usr/bin/env python3
"""LUNC Assistant Bot — full AI assistant for Telegram groups.
Core: summarize hundreds of messages into a quick summary.
Also: /catchup, /tldr, /ask (general AI Q&A), DM summary. Standalone — no other projects included.
Run: TELEGRAM_BOT_TOKEN=... AI_API_KEY=... python bot.py
"""
import os, re, time, json, datetime, pathlib, asyncio
import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions, WebAppInfo, InlineQueryResultGame
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, InlineQueryHandler, filters, ContextTypes
try:
    from telegram.ext import TypeHandler
except Exception:  # test stubs / very old PTB: the usage observer just stays off
    TypeHandler = None
import store, ai_client, burn as burn_mod, chain, lang as lang_mod, ratelimit, budget, modquiz, topics, seclogic, alerts as alerts_mod, github_pr
from kb import kb_as_text, find_kb_answer

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
OWNER_ID = int(os.getenv("OWNER_TELEGRAM_ID", "0") or 0)
# Optional: the bot's own GitHub login, so PR notifications skip events
# it authored itself. Unused when unset.
GITHUB_BOT_LOGIN = os.getenv("GITHUB_BOT_LOGIN", "")
# AI kill switch — True means AI features are live, governed by rank,
# daily caps, and the daily token pot (budget.py: 200,000/day, the Groq
# free allowance). Flip to False to disable ALL AI again. Simple (non-AI)
# commands keep working either way.
AI_ENABLED = True
LCD = "https://terra-classic-lcd.publicnode.com"
BIG_BURN_THRESHOLD = float(os.getenv("BIG_BURN_THRESHOLD_LUNC", "100000000"))

HELP = """🤖 *LUNC Assistant Bot*

*Summaries (main job)*
/summary — last 200 messages
/summary 300 — last 300 messages
/summary 24h / /summary today / /summary 1h
/summary detailed — longer version
/catchup — what you missed since your last /catchup
/tldr — reply to a long message to shrink it

*Ask me*
/ask <question> — ask me anything
Or just @mention me in the group, or DM me

*Live info*
/price — LUNC + USTC price, market cap, volume
/stats — supply, block height, staking %
/convert <amount> LUNC — convert LUNC <-> USD
/proposals — all proposals currently voting
/proposal <id> — proposal detail + live tally
/burn — live burn tax rate + how burns work
/wallet terra1... — public wallet balance + staking
/token terra1... — CW20 token info
/validators — top 10 validators by voting power
/validator <name or terravaloper...> — validator detail

*Staking help*
/stake — how staking works, step by step
/calc <amount> — staking reward ESTIMATE

*Info*
/links — official links only
/dex — DEXes on Luna Classic
/freegames — play Luna Classic games
/safety — scam / seed phrase safety rules
/privacy — what this bot logs, what the AI sees, what it can never do
/learn <word> — plain-English glossary (e.g. /learn quorum)

*Ranks (AI access)*
/rank — your rank + what it unlocks
AI queries: 1 per day for everyone, whatever your rank. Rank 0: starting out · Rank 1: regular (3+ days) · Rank 2: trusted (30+ days) — your rank sets this group's shared daily AI allowance (10/20/30 calls a day). A rank the owner sets by hand (/rankset) still sets that person's own cap (2/4/6 by rank).
Rank is earned by chatting on distinct days (not message count). Owner: /rankset, /rankclear (in groups)

*Daily AI pot*
200,000 tokens a day (the free-plan allowance). When the pot runs out, AI pauses with a "daily limit reached" note until midnight UTC — simple commands and basic summaries keep working.

*AI in this group*
Group admins can turn AI off or on for this group only: /aioff, /aion. Default is on.

*Group protection (opt-in)*
/protect — group admins: request scam protection for this group (the owner approves it)
Protection means: new joiners pass a short safety check in my DM before they can post · accounts on the network's global scam-ban list are removed on sight · a member whose first message contains a link is removed
/gban — reply to a scammer's message (or /gban <user id>): ban them from every protected group
/gunban <user id> — lift a global ban · /gbans — see the ban list
/aiban — reply to an abusive user (or /aiban <user id>): block ALL AI features for them — simple commands still work · /aiunban <user id> lifts it · /aibans lists them
Safety rails on bans: every global ban is written to a permanent log, the owner is alerted instantly with a one-tap undo button, non-owner moderators can global-ban at most 5 people a day, and nobody but the owner can global-ban the owner, an elevated user, or an admin of a protected group. /modlog (owner only) shows the record.
/appeal — in my DM: if you're on the global ban or AI ban list, ask the owner to review it (once a day)
Automatic in protected groups: message flooding = delete + timed mute · the same long message posted across protected groups = deleted + muted + flagged to the owner · brand-new-looking accounts (no username, no profile photo) pass the safety check but start text-only for 24 hours · first-message links to official sites (Finder, LuncScan, Station, Keplr, Ledger) are allowed
Edits and photo/video captions are checked the same way — post clean and swap in a scam link afterwards, and it's treated like posting it. The safety check allows 3 wrong answers before it removes you (you can rejoin and try again)
/mute [minutes] — reply to a member to silence them (default 60 min) · /unmute
/blacklist add <word> — in protected groups, a message containing it is deleted and the sender removed (owner + elevated users)
/muteword add <phrase> — this group only (works with or without protection): a message containing the phrase is deleted and the sender muted 24h · /muteword remove <phrase> · /muteword list (group admins)
/raid on/off — anti-raid lockdown for join surges (also triggers automatically)
/scamalerts on/off — this protected group gets a safety reminder every ~6 hours (group admins)
/banstats — the protection numbers
(Protection controls: protected-group admins, owner-appointed elevated users, and the owner.)

*Hashtags & group texts*
Type a hashtag in chat — #memo, #scammed, #ibctransfer, #safety… — and I'll answer it. #commands lists them all.
/setrules <text> — group admins set this group's rules (/rules or #rules shows them)
/setwelcome <text> — group admins set the note new joiners see (/welcome shows it)
/report — reply to a scam/spam message: alerts this group's admins by DM with a link to it
/faq — this group's saved questions · /faq <question> shows an answer · just typing the question in chat works too
/addfaq — group admins save an FAQ (it walks you through it step by step; /delfaq <question> removes one)
/menu — buttons for the everyday stuff (price, proposals, safety…) — no commands to remember
/panel — group admins: tap switches for AI, scam reminders, and protection

*Notifications (your choice, on/off)*
/burnalerts — burn notifications menu (master on/off + types)
/govalerts — proposal / voting notifications menu (new, ending soon, result)
/pr <owner/repo> <number> — GitHub pull request info (or /pr <PR link>, or just /pr <number> if this chat watches one repo)
/pralerts on/off — GitHub PR notifications for this chat (new PRs, comments, reviews, merges)
/prwatch — GitHub repos this chat follows · /prwatch add <owner/repo> · /prwatch remove <owner/repo>
/watchvalidator <name or terravaloper...> — watch a validator in this chat
/unwatchvalidator <terravaloper...> — stop watching
/watchlist — validators watched in this chat
/settings — notification menus hub
In a group, only admins can change group settings. In DM, it's just for you.

*Other*
/language — choose your language (summaries + answers follow it)
/help — this list
In DM: forward / paste any long text and I'll summarize it.
"""

def parse_summary_args(args, chat_id):
    detailed = "detailed" in args
    args = [a for a in args if a != "detailed"]
    now = int(time.time())
    if not args:
        return store.get_messages(chat_id, limit=200), detailed
    a = args[0].lower()
    if a in ("today",): return store.get_messages(chat_id, limit=1000, since_ts=now - (now % 86400)), detailed
    if a.endswith("h"):
        try: return store.get_messages(chat_id, limit=1000, since_ts=now - int(a[:-1])*3600), detailed
        except: pass
    if a.endswith("d"):
        try: return store.get_messages(chat_id, limit=1000, since_ts=now - int(a[:-1])*86400), detailed
        except: pass
    try: return store.get_messages(chat_id, limit=int(a)), detailed
    except: return store.get_messages(chat_id, limit=200), detailed

async def send_long(update, text):
    for i in range(0, len(text), 3900):
        await update.effective_message.reply_text(text[i:i+3900])

USAGE_HONESTY_NOTE = ("Counts are what the bot has actually seen since usage tracking began. "
    "Telegram gives bots no list of their chats, so a group that never sends anything — and was "
    "added before tracking started — stays invisible until it stirs.")

def format_usage_report(counts, legacy, pot_spent, pot_budget, heading="📊 *LUNC Assistant — daily usage*"):
    """Owner usage report — aggregate COUNTS ONLY (no group names, no
    user names, ever). `counts` is store.registry_counts(); `legacy`
    is the old log-based store.usage_counts(), kept as a clearly
    labeled secondary line. Pot figures are a UTC-day estimate (the
    pot resets at midnight UTC, the report day is America/New_York)."""
    i = counts["interactions_today"]
    return (
        f"{heading} — {counts['day']} (America/New_York)\n"
        f"Groups I'm in: {counts['groups_member']} confirmed"
        f" · +{counts['groups_unknown']} known but unconfirmed"
        f" · {counts['groups_left']} known to have removed me\n"
        f"Groups active today: {counts['groups_active_today']} · New groups today: {counts['new_groups_today']}\n"
        f"People known: {counts['people_total']} (DM: {counts['people_dm_total']} · groups: {counts['people_group_total']})\n"
        f"People active today: {counts['people_active_today']} · New people today: {counts['new_people_today']}\n"
        f"DM users active today: {counts['dm_active_today']}\n"
        f"Interactions today: {counts['interactions_total']} "
        f"(commands {i['command']} · messages {i['message']} · button taps {i['button']} · other {i['other']})\n"
        f"Messages currently logged (7-day rolling): {counts['messages_logged']:,}\n"
        f"AI pot today (UTC day, estimate): {pot_spent:,} / {pot_budget:,} tokens\n"
        f"Older log-based view (7-day message log only): {legacy['groups']} groups with logged messages"
        f" · {legacy['people_in_groups']} people in them · {legacy['dm_users']} DM users\n"
        f"{USAGE_HONESTY_NOTE}")

async def on_botstats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    # Owner-only usage counter (not in the public command list).
    if not OWNER_ID or update.effective_user.id != OWNER_ID:
        return
    text = format_usage_report(store.registry_counts(), store.usage_counts(),
                               budget.spent(), budget.DAILY_TOKEN_BUDGET,
                               heading="📊 *Bot usage*")
    await update.effective_message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

def _classify_update(update):
    """Broad interaction kind for the usage counters: command /
    message / button (callback tap) / other. Pure + defensive so it
    can be unit-tested on fake updates."""
    try:
        if getattr(update, "callback_query", None) is not None:
            return "button"
        msg = getattr(update, "message", None) or getattr(update, "edited_message", None)
        if msg is not None:
            text = getattr(msg, "text", None) or ""
            for e in (getattr(msg, "entities", None) or []):
                if getattr(e, "type", None) == "bot_command" and getattr(e, "offset", 0) == 0:
                    return "command"
            return "command" if text.startswith("/") else "message"
    except Exception:
        pass
    return "other"

async def on_observe_update(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Passive usage observer (group -1, runs before every handler).

    Records ONLY metadata into the usage registry: which chat/user an
    update came from, the broad interaction kind, and bot-membership
    changes (my_chat_member). Never reads or stores message text or
    names for the registry. Wrapped so it can NEVER break a real
    handler: any failure is swallowed silently.
    """
    try:
        chat = update.effective_chat
        user = update.effective_user
        is_member = None
        mcm = getattr(update, "my_chat_member", None)
        if mcm is not None:
            new = getattr(mcm, "new_chat_member", None)
            status = getattr(new, "status", None)
            if status in ("member", "administrator"):
                is_member = True
            elif status in ("left", "kicked"):
                is_member = False
            elif status == "restricted":
                is_member = bool(getattr(new, "is_member", False))
        # Join/leave service messages: the chat stirred, but a member
        # merely joining did not "use the bot" — count no user.
        record_user = True
        msg = getattr(update, "message", None)
        if msg is not None and (getattr(msg, "new_chat_members", None) or getattr(msg, "left_chat_member", None)):
            record_user = False
        if user is not None and ctx is not None and getattr(ctx, "bot", None) is not None and user.id == ctx.bot.id:
            return  # never count the bot itself
        store.observe_update(
            chat_id=chat.id if chat is not None else None,
            chat_type=getattr(chat, "type", None) if chat is not None else None,
            user_id=user.id if user is not None else None,
            user_is_bot=bool(getattr(user, "is_bot", False)) if user is not None else False,
            kind=_classify_update(update),
            is_member=is_member,
            record_user=record_user)
    except Exception:
        pass

async def job_usage_report(ctx: ContextTypes.DEFAULT_TYPE):
    """Owner daily usage DM at 7:00 PM America/New_York.

    Runs every 15 minutes and self-heals: it sends only when the ET
    clock is at/after 19:00 AND the persisted last-sent day is not
    today, so a restart near 7 PM neither misses nor duplicates the
    report. The last-sent marker is written only AFTER a successful
    send, so a failed send retries on the next tick.
    """
    try:
        if not OWNER_ID:
            return
        today = store.et_day()
        now_et = datetime.datetime.now(store._ET)
        if now_et.hour < 19:
            return
        if store.get_setting(0, "usage_report_day") == today:
            return
        text = format_usage_report(store.registry_counts(), store.usage_counts(),
                                   budget.spent(), budget.DAILY_TOKEN_BUDGET)
        await ctx.bot.send_message(OWNER_ID, text, parse_mode=ParseMode.MARKDOWN)
        store.set_setting(0, "usage_report_day", today)
    except Exception:
        pass

def user_lang(update):
    """The requester's language. Personal, never a group setting: one user
    switching language never changes what anyone else sees."""
    return store.get_user_lang(update.effective_user.id)

async def on_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    # Captcha entry: a muted new joiner in a protected group lands here.
    pend = store.captcha_for_user(update.effective_user.id)
    if pend is not None:
        await _start_quiz(update, ctx, pend)
        return
    if ctx.args and ctx.args[0] == "captcha":
        await update.effective_message.reply_text("You don't have a pending safety check right now. If you just joined a protected group, tap the button in the group's welcome message to start it.")
        return
    lg = user_lang(update)
    await update.effective_message.reply_text(lang_mod.t("intro", lg), reply_markup=lang_mod.lang_keyboard())

async def on_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(HELP, parse_mode=ParseMode.MARKDOWN)

async def on_language(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lg = user_lang(update)
    await update.effective_message.reply_text(lang_mod.t("current", lg, name=lang_mod.LABELS[lg]),
                                    reply_markup=lang_mod.lang_keyboard())

async def on_rank(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Anyone's own rank + what it unlocks. Not an AI call."""
    chat, user = update.effective_chat, update.effective_user
    if chat.type == "private":
        rank = store.rank_anywhere(user.id)
        days = store.days_active_anywhere(user.id)
        scope, override = "across all groups I log", None
    else:
        rank, days, override = store.rank_info(chat.id, user.id)
        scope = "in this chat"
    if rank == 0:
        unlocks = "AI queries: 1 per day for everyone — rank no longer raises the personal limit. Your rank sets this chat's shared AI allowance: 10 calls/day at rank 0. Chat on 3 different days to reach rank 1 (20/day for the chat)."
    elif rank == 1:
        unlocks = "AI queries: 1 per day for everyone — rank no longer raises the personal limit. Your rank gives this chat a shared AI allowance of 20 calls/day. Chat on 30 different days to reach rank 2 (30/day for the chat)."
    else:
        unlocks = "AI queries: 1 per day for everyone — rank no longer raises the personal limit. Your rank gives this chat the top shared AI allowance: 30 calls/day."
    if override is not None:
        unlocks += " Your rank was set by the owner, so your own AI cap follows the set rank instead (2/4/6 per day by rank)."
    extra = " (set by the owner)" if override is not None else ""
    await update.effective_message.reply_text(
        f"🎖 Your rank {scope}: {rank}{extra}\n"
        f"Distinct days active: {days} (rank 1 at {store.RANK_DAYS_1}, rank 2 at {store.RANK_DAYS_2})\n{unlocks}")

def _rankset_target(update, ctx):
    """(user_id, rank, error) from a reply or from args. rank=None for /rankclear."""
    msg = update.message
    args = ctx.args or []
    if msg.reply_to_message and msg.reply_to_message.from_user:
        target = msg.reply_to_message.from_user.id
        rank_s = args[0] if args else None
    elif len(args) >= 2:
        try:
            target = int(args[0])
        except (TypeError, ValueError):
            target = None
        rank_s = args[1]
    elif len(args) == 1:
        try:
            target = int(args[0])
        except (TypeError, ValueError):
            target = None
        rank_s = None
    else:
        target, rank_s = None, None
    return target, rank_s

async def on_rankset(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Owner-only, groups only: /rankset <0|1|2> as a reply, or /rankset <user_id> <0|1|2>."""
    if update.effective_user.id != OWNER_ID:
        await update.effective_message.reply_text("🔒 Only the bot owner can set ranks."); return
    if update.effective_chat.type == "private":
        await update.effective_message.reply_text("Run /rankset in the group the rank belongs to."); return
    target, rank_s = _rankset_target(update, ctx)
    if target is None or rank_s is None:
        await update.effective_message.reply_text("Usage: reply to someone's message with /rankset <0|1|2>, or /rankset <user_id> <0|1|2>."); return
    try:
        rank = int(rank_s)
    except (TypeError, ValueError):
        await update.effective_message.reply_text("Rank must be 0, 1 or 2."); return
    if rank not in (0, 1, 2):
        await update.effective_message.reply_text("Rank must be 0, 1 or 2."); return
    store.set_rank_override(update.effective_chat.id, target, rank, update.effective_user.id)
    await update.effective_message.reply_text(f"✅ Rank set to {rank} for user {target} in this chat.")

async def on_rankclear(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Owner-only, groups only: drop a manual rank so the earned rank applies again."""
    if update.effective_user.id != OWNER_ID:
        await update.effective_message.reply_text("🔒 Only the bot owner can clear ranks."); return
    if update.effective_chat.type == "private":
        await update.effective_message.reply_text("Run /rankclear in the group the rank belongs to."); return
    target, _ = _rankset_target(update, ctx)
    if target is None:
        await update.effective_message.reply_text("Usage: reply to someone's message with /rankclear, or /rankclear <user_id>."); return
    n = store.clear_rank_override(update.effective_chat.id, target)
    if n:
        await update.effective_message.reply_text(f"✅ Manual rank cleared for user {target} — their earned rank applies again.")
    else:
        await update.effective_message.reply_text("No manual rank was set for that user — their earned rank already applies.")

async def on_lang_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    code = (q.data or "").split(":", 1)[1] if ":" in (q.data or "") else ""
    if code not in lang_mod.CODES:
        await q.answer("Unknown language."); return
    if code == user_lang(update):
        await q.answer("Already set."); return
    store.set_user_lang(update.effective_user.id, code)
    await q.answer()
    try:
        await q.edit_message_text(lang_mod.t("picked", code, name=lang_mod.LABELS[code]),
                                  reply_markup=lang_mod.lang_keyboard())
    except BadRequest as e:
        if "Message is not modified" not in str(e):
            raise

AI_BANNED_NOTE = (
    "🚫 AI is off for your account — a moderator put an AI ban on it. "
    "Simple commands still work: /price, /validators, /proposals, /links, /calc, /stake, /safety. "
    "If you think this is a mistake, ask a group admin or the bot owner.")

GROUP_AI_OFF_NOTE = (
    "🔒 AI is turned off in this group by its admins. Simple commands still work: "
    "/price, /validators, /proposals, /links, /calc, /stake, /safety. "
    "An admin can turn AI back on with /aion.")

async def ai_guard(update):
    """AI gate: kill switch, then the group's own AI switch, then the
    caller's AI ban, then the daily caps — 1 AI call per user per day
    for everyone (an owner-set rank override keeps the 2/4/6 ladder for
    that person), plus the per-chat caps (10/20/30 by rank).
    False = message already sent."""
    if not AI_ENABLED:
        await update.effective_message.reply_text(
            "🤖 AI features are temporarily disabled while we review security. "
            "Simple commands still work: /price, /validators, /proposals, /links, /calc, /stake, /safety. /summary and /catchup also work as basic non-AI summaries while AI is off.")
        return False
    if update.effective_chat.type != "private" and not store.ai_enabled(update.effective_chat.id):
        await update.effective_message.reply_text(GROUP_AI_OFF_NOTE)
        return False
    user_id = update.effective_user.id
    chat = update.effective_chat
    if user_id != OWNER_ID and store.is_ai_banned(user_id):
        await update.effective_message.reply_text(AI_BANNED_NOTE)
        return False
    if chat.type == "private":
        rank = store.rank_anywhere(user_id)
        overridden = False  # rank overrides are per-group; DM rank is earned-only
    else:
        rank, _days, override = store.rank_info(chat.id, user_id)
        overridden = override is not None
    if ratelimit.allowed_for_rank(user_id, chat.id, OWNER_ID, rank=rank, overridden=overridden):
        return True
    if overridden:
        note = ("⏳ You've hit your daily AI limit — it resets at midnight UTC. "
                "(Your rank was set by the owner, so your cap follows it; daily caps protect the bot's AI quota from spam.)")
    else:
        note = ("⏳ You've hit your daily AI limit — one AI question per day for everyone, "
                "and it resets at midnight UTC. (This cap protects the bot's AI quota from spam.)")
    await update.effective_message.reply_text(note)
    return False

FALLBACK_NOTE = "📋 Basic summary (AI is off — no AI used):\n\n"

def fallback_text(rows, detailed=False):
    """Local extractive summary for when AI is off. Zero tokens, no AI call,
    so rank, rate limits, and the daily pot (which protect the Groq quota)
    do not apply to it."""
    return FALLBACK_NOTE + ai_client.extractive_summary(rows, detailed=detailed)

async def on_summary(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    rows, detailed = parse_summary_args(ctx.args, update.effective_chat.id)
    if not rows:
        await update.effective_message.reply_text("No messages logged yet — I can only summarize messages sent after I joined this group. Give it some activity, then try /summary again.")
        return
    if not AI_ENABLED:
        await send_long(update, fallback_text(rows, detailed=detailed))
        store.set_catchup(update.effective_chat.id, update.effective_user.id)
        return
    if not await ai_guard(update): return
    await update.effective_message.reply_text(f"Summarizing {len(rows)} messages…")
    out = await ai_client.summarize(rows, detailed=detailed, lang=user_lang(update))
    await send_long(update, out)
    store.set_catchup(update.effective_chat.id, update.effective_user.id)

async def on_catchup(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid, uid = update.effective_chat.id, update.effective_user.id
    last = store.get_catchup_id(cid, uid)
    if last is None:
        rows = store.get_messages(cid, limit=200)
        await update.effective_message.reply_text("First catchup — here's the last 200, and I'll track from here next time.")
    else:
        rows = store.get_messages(cid, limit=1000, after_id=last)
    if not rows:
        await update.effective_message.reply_text("You're all caught up — no new messages since your last /catchup.")
        return
    if not AI_ENABLED:
        await send_long(update, f"📬 Catchup — {len(rows)} new messages (basic summary, AI off)\n\n{ai_client.extractive_summary(rows)}")
        store.set_catchup(cid, uid)
        return
    if not await ai_guard(update): return
    out = await ai_client.summarize(rows, lang=user_lang(update))
    await send_long(update, f"📬 Catchup — {len(rows)} new messages\n\n{out}")
    store.set_catchup(cid, uid)

async def on_tldr(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message.reply_to_message
    if not msg or not msg.text:
        await update.effective_message.reply_text("Reply to a long message with /tldr and I'll shrink it.")
        return
    if not await ai_guard(update): return
    out = await ai_client.chat([
        {"role":"system","content":"Summarize the message in 2-3 short lines. No extra commentary."},
        {"role":"user","content": msg.text}], lang=user_lang(update))
    if not out:
        out = ai_client.DAILY_LIMIT_NOTE if budget.exhausted() else msg.text[:400]
    await update.effective_message.reply_text(f"⚡ TL;DR: {out}")

async def on_ask(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = " ".join(ctx.args).strip()
    if not q:
        await update.effective_message.reply_text("Ask me something: /ask explain this proposal in simple words")
        return
    if not await ai_guard(update): return
    out = await ai_client.chat([
        {"role":"system","content":"You are LUNC Assistant Bot, a standalone general AI assistant for Telegram groups. Answer clearly and concisely. Do not invent contract addresses or claim knowledge of any specific project. Trusted references you may cite: Finder (finder.terra.money/classic) for on-chain verification, LuncScan (luncscan.com) for explorer data and beginner staking/validator guides, LUNCDash (luncdash.com) for dashboards, and StatsBin (statsbin.com) for chain stats and upgrade countdowns. Terra Classic validators discuss governance and day-to-day operations in the Transparent Validator Chat on Telegram (t.me/transparentvalidatorchat)."},
        {"role":"user","content": q}], lang=user_lang(update))
    if not out:
        out = ai_client.DAILY_LIMIT_NOTE if budget.exhausted() else "AI isn't configured yet (no AI_API_KEY). The owner can add the key in Railway and I'll answer fully."
    await send_long(update, out)


def burn_keyboard(chat_id):
    s = store.burn_settings(chat_id)
    def lbl(key, name):
        return f"{chr(9989) if s[key]=='on' else chr(10060)} {name}"
    master = s["burn_alerts"]
    kb = [
        [InlineKeyboardButton(lbl("burn_alerts", "Burn notifications (master)"), callback_data="burn:burn_alerts")],
        [InlineKeyboardButton(lbl("burn_daily", "Daily burn report"), callback_data="burn:burn_daily"),
         InlineKeyboardButton(lbl("burn_big", "Big burns"), callback_data="burn:burn_big")],
        [InlineKeyboardButton(lbl("burn_rate", "Burn tax rate changes"), callback_data="burn:burn_rate")],
    ]
    return InlineKeyboardMarkup(kb), master

def burn_status_text(chat_id):
    s = store.burn_settings(chat_id)
    state = "ON" if s["burn_alerts"]=="on" else "OFF"
    return (f"🔥 *Burn notifications: {state}* for this chat\n"
            f"Tap to turn on/off. Types only fire when the master switch is ON.\n"
            f"• Daily burn report: {s['burn_daily']}\n"
            f"• Big burns (supply drop ≥ {BIG_BURN_THRESHOLD:,.0f} LUNC between checks): {s['burn_big']}\n"
            f"• Burn tax rate changes: {s['burn_rate']}")

async def _can_change(update, ctx):
    chat = update.effective_chat
    if chat.type == "private": return True
    try:
        m = await ctx.bot.get_chat_member(chat.id, update.effective_user.id)
        return m.status in ("administrator", "creator")
    except Exception:
        return False

async def on_burn(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    rate = await burn_mod.get_burn_tax_rate()
    await update.effective_message.reply_text(burn_mod.burn_explainer(rate), parse_mode=ParseMode.MARKDOWN)

async def on_burnalerts(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    if ctx.args and ctx.args[0].lower() in ("on", "off"):
        if not await _can_change(update, ctx):
            await update.effective_message.reply_text("Only group admins can change this group's settings."); return
        store.set_setting(cid, "burn_alerts", ctx.args[0].lower())
    kb, _ = burn_keyboard(cid)
    await update.effective_message.reply_text(burn_status_text(cid), reply_markup=kb, parse_mode=ParseMode.MARKDOWN)

async def on_burn_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not await _can_change(update, ctx):
        await q.answer("Only group admins can change group settings.", show_alert=True); return
    key = q.data.split(":", 1)[1]
    cid = q.message.chat.id
    cur = store.get_setting(cid, key)
    store.set_setting(cid, key, "off" if cur == "on" else "on")
    await q.answer(f"{key}: {'OFF' if cur=='on' else 'ON'}")
    kb, _ = burn_keyboard(cid)
    await q.edit_message_text(burn_status_text(cid), reply_markup=kb, parse_mode=ParseMode.MARKDOWN)


# ================= TOP PACK: live info =================
async def price_text():
    try:
        d = await chain.prices()
        return "💰 *Prices — live (CoinGecko)*\n" + chain.fmt_price(d["terra-luna"], "LUNC") + "\n" + chain.fmt_price(d["terrausd"], "USTC")
    except Exception:
        return "Couldn't fetch prices right now."

async def on_price2(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(await price_text(), parse_mode=ParseMode.MARKDOWN)

async def on_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try: await update.effective_message.reply_text(await chain.stats_text(), parse_mode=ParseMode.MARKDOWN)
    except Exception: await update.effective_message.reply_text("Couldn't fetch chain stats right now.")

async def on_convert(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.effective_message.reply_text("Usage: /convert 1000000  (LUNC amount)  or  /convert 10 usd"); return
    try:
        amt = float(ctx.args[0].replace(",", "")); d = await chain.prices(); price = d["terra-luna"]["usd"]
        if len(ctx.args) > 1 and ctx.args[1].lower() == "usd":
            await update.effective_message.reply_text(f"${amt:,.2f} ≈ {amt/price:,.0f} LUNC (at ${price:.8g}, CoinGecko)")
        else:
            await update.effective_message.reply_text(f"{amt:,.0f} LUNC ≈ ${amt*price:,.2f} (at ${price:.8g}, CoinGecko)")
    except Exception: await update.effective_message.reply_text("Couldn't convert right now — check the amount format.")

async def proposals_text():
    try:
        props = await chain.proposals_voting()
    except Exception:
        return "Couldn't fetch proposals right now."
    if not props:
        return "No proposals are in the voting period right now."
    lines = ["🗳️ *Proposals currently voting:*"]
    for pr in props:
        lines.append(f"\n*{pr['id']}* — {pr.get('title','(no title)')}\nVoting ends: {pr.get('voting_end_time','')} UTC\nUse /proposal {pr['id']} for the tally")
    return "\n".join(lines)

async def on_proposals(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await send_long(update, await proposals_text())

async def on_wallet(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args: await update.effective_message.reply_text("Usage: /wallet terra1..."); return
    try: await update.effective_message.reply_text(await chain.wallet_text(ctx.args[0]), parse_mode=ParseMode.MARKDOWN)
    except Exception: await update.effective_message.reply_text("Couldn't fetch that wallet right now.")

async def on_token(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args: await update.effective_message.reply_text("Usage: /token terra1... (CW20 contract)"); return
    await update.effective_message.reply_text(await chain.token_text(ctx.args[0]), parse_mode=ParseMode.MARKDOWN)

async def on_validators(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        vals = await chain.validators_top(10)
        lines = ["🏛️ *Top 10 validators by voting power*"]
        for i, v in enumerate(vals, 1):
            lines.append(f"{i}. {v['description']['moniker']} — {int(v['tokens'])/1e6:,.0f} LUNC, commission {float(v['commission']['commission_rates']['rate'])*100:.1f}%")
        lines.append("\nDetail: /validator <name>   Watch one: /watchvalidator <name>")
        await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
    except Exception: await update.effective_message.reply_text("Couldn't fetch validators right now.")

async def on_validator_info(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args: await update.effective_message.reply_text("Usage: /validator <moniker or terravaloper...>"); return
    try:
        v = await chain.find_validator(" ".join(ctx.args))
        if not v: await update.effective_message.reply_text("Validator not found — check the name or use the terravaloper address."); return
        await update.effective_message.reply_text(chain.validator_text(v), parse_mode=ParseMode.MARKDOWN)
    except Exception: await update.effective_message.reply_text("Couldn't fetch that validator right now.")

STAKE_TEXT = """🥩 *How LUNC staking works*
1. Hold LUNC in a wallet you control (Galaxy Station, Keplr, Leap).
2. Pick a validator — check commission, uptime, and voting record (/validators). Smaller validators help decentralisation.
3. Delegate (stake) your LUNC to them. You can split across validators.
4. You earn rewards in LUNC; claim them in your wallet app.
5. Unbonding takes *21 days* — during that time LUNC earns nothing and can't move.
6. Redelegating moves stake to another validator instantly (then a 21-day cooldown for that amount).
Risks: validator downtime/slashing can cost a small %; price can move while unbonding. This is info, not financial advice."""

async def on_stake(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(STAKE_TEXT, parse_mode=ParseMode.MARKDOWN)

async def on_calc(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args: await update.effective_message.reply_text("Usage: /calc 1000000 — reward estimate for staking that many LUNC for 1 year"); return
    try:
        amt = float(ctx.args[0].replace(",", ""))
        # Estimate only: bonded ratio method is complex on-chain; use a clearly-labelled range via supply inflation proxy is unreliable,
        # so present a simple scenario table instead of a fake precise APR.
        lines = [f"🧮 *Reward ESTIMATE for {amt:,.0f} LUNC over 1 year* (before validator commission, not a promise):"]
        for apr in (2, 3.5, 5, 7):
            lines.append(f"• At {apr}% APR: ~{amt*apr/100:,.0f} LUNC")
        lines.append("Actual APR moves with staking ratio, tax, and commission — check your wallet app for the live rate before staking.")
        await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
    except Exception: await update.effective_message.reply_text("Check the amount — example: /calc 1000000")

LINKS_TEXT = """🔗 *Official links only*
Terra Classic: https://terra-classic.io (community)
Block explorer / Finder: https://finder.terra.money/classic
Galaxy Station wallet: https://station.terraclassic.community
Keplr wallet: https://www.keplr.app
Cosmostation wallet: https://chromewebstore.google.com/detail/fpkhgmpbidmiogeglndfbkegfdlnajnf
LUNCDash: https://luncdash.com
LuncScan (explorer + staking guides): https://luncscan.com
Community stats — StatsBin (chain stats + upgrade countdown): https://statsbin.com (X: https://x.com/StatsBin)
Governance forum: https://discuss.terra-classic.io (verify current forum in chat)
Terra Classic docs / GitHub: https://github.com/classic-terra
CoinGecko LUNC: https://www.coingecko.com/en/coins/terra-luna
Community — Transparent Validator Chat (Telegram): https://t.me/transparentvalidatorchat
⚠️ Bookmark these. Scam copies of all of them exist — never trust a link DM'd to you."""

SAFETY_TEXT = """🛡️ *Safety rules*
• NEVER share your seed phrase / private key. No admin, validator, or bot will ever ask. This bot never will.
• Admins never DM you first with airdrops, support, or wallet fixes.
• Verify every contract / wallet address on Finder before sending.
• A token being listed or named in chat is NOT verification it's safe.
• Use a fresh wallet for experiments; keep main funds separate.
• If it's urgent and guaranteed profit, it's a scam."""

GLOSSARY = {
 "quorum": "Minimum share of total voting power that must vote for a proposal result to count. Terra Classic quorum is 40% of bonded stake.",
 "veto": "NO WITH VETO: if veto passes 33.4% of non-abstain votes, the proposal is rejected AND its deposit is burned.",
 "unbonding": "After you unstake, LUNC is locked for 21 days — no rewards, can't transfer — then returns to your wallet.",
 "cw20": "The token standard for fungible tokens on Terra Classic (like ERC-20). Each token is a smart contract.",
 "validator": "Node operator who produces blocks and votes on governance. Delegators stake LUNC to them and share rewards minus commission.",
 "delegation": "Staking LUNC to a validator. Your LUNC stays yours; the validator can't spend it, but downtime/slashing can cost a small %.",
 "tally": "The live vote count on a proposal: YES / NO / NO WITH VETO / ABSTAIN, weighted by staked LUNC.",
 "burn tax": "Terra Classic on-chain tax (live rate via /burn): currently 1.5% total, 80% burned = 1.2% of taxable flow.",
}

DEX_TEXT = """🔄 *DEXes on Luna Classic*
• Terraport — swaps, liquidity pools, farming: https://terraport.finance
• Terraswap Classic — the original community DEX: https://app.terraswap.io
• Garuda DeFi DEX — built natively on Terra Classic: https://garuda-defi.org
• CL8Y DEX: https://dex.cl8y.com
• WESO: https://wesoworld.io
Charts for Classic pairs: Coinhall https://coinhall.org · Vyntrex https://vyntrex.io
⚠️ Open a DEX from your own bookmark only — fake DEX sites are a common drain. Check a pair's contract address on Finder before you swap."""

async def on_links(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(LINKS_TEXT, parse_mode=ParseMode.MARKDOWN)

async def on_dex(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(DEX_TEXT, parse_mode=ParseMode.MARKDOWN)

GAMES_TEXT = (
    "🎮 *Luna Classic games*\n\n"
    "🏎 *NEON RUSH* — neon highway racer. Dodge the traffic, chain near misses, and grab LUNC + USTC coins — they're your fuel, run dry and the run ends. Global leaderboard inside the game.\n\n"
    "🃏 *SOLITAIRE* — classic Klondike. Drag cards or tap to auto-move, double-tap sends a card home. Stars light up as you get cards home.\n\n"
    "🏀 *HOOPS* — flick Luna Classic tokens into the hoop. The little flame-haired guy does the shooting: drag back to aim, let go to throw. Baskets build a score multiplier; you've got 3 tokens and 3 minutes.\n\n"
    "⚽ *PENALTY KICK* — ten kicks from the spot. Drag back and release to shoot, string goals together to raise the streak multiplier — and top corners count double.\n\n"
    "🎯 *DARTS* — hold to aim the swaying crosshair, let go to throw. Rings pay up to 25 and the gold bull is 50.\n\n"
    "🧩 *LUNA BLOCKS* — drag pieces onto the board, fill rows and columns to clear them. Clear 2+ lines in one move to unlock the golden Luna piece.\n\n"
    "⛳ *LUNA GOLF* — 9 holes of lunar mini golf. Drag to aim, release to putt — dodge the dust traps and patrol rocks and chase the ace. Low strokes, high score.\n\n"
    "🚀 *LUNA DEFENDER* — defend the moon base! Drag to steer your ship, blast asteroids and drones, catch the falling LUNC coins, and survive the boss rock every 5th wave.\n\n"
    "🏗 *LUNA TOWER* — stack the habitat modules as high as you can. Tap to drop the sliding block — perfect drops build combos and keep your tower wide.\n\n"
    "🐍 *LUNA SNAKE* — the classic, on the Moon. Steer the little rover train, eat LUNC coins to grow, grab the rare USTC token — just don't hit the walls or yourself.\n\n"
    "🚀 *LUNA FLAP* — one-tap flying. Tap to flap the little moon lander through the crater pillars. Thread a gate for +10 and snatch the coins floating in the gaps.\n\n"
    "🎪 *LUNA PINBALL* — a moon-base pinball table. Launch the ball, work the flippers, light up the LUNC bumpers and the target bank. Three balls — make them count.\n\n"
    "🏎 *LUNA RACER* — full-throttle moon racing. Weave the winding lunar road, sweep up the LUNC coin arcs, snatch the rare USTC tokens, and don't trade paint with the rocks.\n\n"
    "💥 *LUNA CANNON* — moon artillery. Drag to aim the arc and fire LUNC shells at the USTC targets. A direct hit pays 50 and a double pays bonus — 3 rounds, 8 shells each.\n\n"
    "👽 *LUNA WHACK* — 60 seconds, nine craters. Whack the LUNC token critters and the rare USTC ones, build your streak multiplier — and whatever you do, don't tap the bombs.\n\n"
    "🏍 *LUNA RIDER* — motorcycle trials on the Moon. Feather the throttle over six brutal stages of ramps and gaps. Land backflips for bonus points without landing on your head.\n\n"
    "🎱 *LUNA POOL* — moon pool. Pull back, aim, and sink all 8 moon balls in as few shots as you can. Every ball is worth 100 and clearing the rack pays a 250 bonus.\n\n"
    "🧟 *ZOMBIE DEFENSE* — the horde is coming for the moon base. Hold three lanes, blast the waves, and spend your points on upgrades between rounds.\n\n"
    "🧱 *LUNA BREAKOUT* — the arcade classic, Luna style. Smash the brick wall with paddle and ball — and when the glowing LUNC block drops, the whole wall lights up.\n\n"
    "🧗 *LUNA CLIMB* — bounce to the Moon! Ride the moon-rock platforms higher and higher — grab a jetpack, propeller cap, shield or coin magnet, stomp the comet critters, and beat your own best-height flag.\n\n"
    "Tap a game to play — it opens right here in Telegram.")
NEON_RUSH_URL = "https://frg-fight-club.vercel.app/neon-rush/"
SOLITAIRE_URL = "https://frg-fight-club.vercel.app/solitaire/"
HOOPS_URL = "https://frg-fight-club.vercel.app/hoops/"
PENALTY_URL = "https://frg-fight-club.vercel.app/penalty/"
DARTS_URL = "https://frg-fight-club.vercel.app/darts/"
BLOCKS_URL = "https://frg-fight-club.vercel.app/blocks/"
GOLF_URL = "https://frg-fight-club.vercel.app/golf/"
DEFENDER_URL = "https://frg-fight-club.vercel.app/defender/"
TOWER_URL = "https://frg-fight-club.vercel.app/tower/"
SNAKE_URL = "https://frg-fight-club.vercel.app/snake/"
FLAP_URL = "https://frg-fight-club.vercel.app/flap/"
PINBALL_URL = "https://frg-fight-club.vercel.app/pinball/"
RACER_URL = "https://frg-fight-club.vercel.app/racer/"
CANNON_URL = "https://frg-fight-club.vercel.app/cannon/"
WHACK_URL = "https://frg-fight-club.vercel.app/whack/"
RIDER_URL = "https://frg-fight-club.vercel.app/luna-rider/"
POOL_URL = "https://frg-fight-club.vercel.app/pool/"
ZOMBIE_URL = "https://frg-fight-club.vercel.app/zombie/"
BREAKOUT_URL = "https://frg-fight-club.vercel.app/breakout/"
CLIMB_URL = "https://frg-fight-club.vercel.app/climb/"

# Native Telegram Games (registered in BotFather for this bot). The short
# names are the identifiers Telegram sends back when a player taps Play.
TELEGRAM_GAMES = (
    ("neonrush", "🏎 NEON RUSH", NEON_RUSH_URL),
    ("solitaire", "🃏 SOLITAIRE", SOLITAIRE_URL),
    ("hoops", "🏀 HOOPS", HOOPS_URL),
    ("Penalty", "⚽ PENALTY KICK", PENALTY_URL),
    ("Darts", "🎯 DARTS", DARTS_URL),
    ("LunaBlocks", "🧩 LUNA BLOCKS", BLOCKS_URL),
    ("Lunagolf", "⛳ LUNA GOLF", GOLF_URL),
    ("LunaDefender", "🚀 LUNA DEFENDER", DEFENDER_URL),
    ("LunaTower", "🏗 LUNA TOWER", TOWER_URL),
    ("LunaSnake", "🐍 LUNA SNAKE", SNAKE_URL),
    ("LunaFlap", "🚀 LUNA FLAP", FLAP_URL),
    ("LunaPinball", "🎪 LUNA PINBALL", PINBALL_URL),
    ("LunaRacer", "🏎 LUNA RACER", RACER_URL),
    ("LunaCannon", "💥 LUNA CANNON", CANNON_URL),
    ("LunaWhack", "👽 LUNA WHACK", WHACK_URL),
    ("LunaRider", "🏍 LUNA RIDER", RIDER_URL),
    ("LunaPool", "🎱 LUNA POOL", POOL_URL),
    ("ZOMBIEDEFENSE", "🧟 ZOMBIE DEFENSE", ZOMBIE_URL),
    ("LunaBreakout", "🧱 LUNA BREAKOUT", BREAKOUT_URL),
    ("LUNACLIMB", "🧗 LUNA CLIMB", CLIMB_URL),
)
GAME_URL_BY_SHORT_NAME = {short: url for short, _, url in TELEGRAM_GAMES}
# Telegram echoes the short name exactly as registered in BotFather, which
# may differ in case from the lowercase names used to send the card.
GAME_URL_BY_SHORT_NAME_CI = {short.lower(): url for short, url in GAME_URL_BY_SHORT_NAME.items()}

# Public leaderboard APIs for the games (same Vercel project as the
# game pages). The group /games post carries each game's Top 5 under the
# cards; the full Top 20 board lives inside each game.
GAME_BOARD_APIS = (
    ("neonrush", "🏎 *NEON RUSH*", "https://frg-fight-club.vercel.app/api/neon-rush-board"),
    ("solitaire", "🃏 *SOLITAIRE*", "https://frg-fight-club.vercel.app/api/solitaire-board"),
    ("hoops", "🏀 *HOOPS*", "https://frg-fight-club.vercel.app/api/hoops-board"),
    ("Penalty", "⚽ *PENALTY KICK*", "https://frg-fight-club.vercel.app/api/luna-games?game=penalty"),
    ("Darts", "🎯 *DARTS*", "https://frg-fight-club.vercel.app/api/luna-games?game=darts"),
    ("LunaBlocks", "🧩 *LUNA BLOCKS*", "https://frg-fight-club.vercel.app/api/luna-games?game=blocks"),
    ("Lunagolf", "⛳ *LUNA GOLF*", "https://frg-fight-club.vercel.app/api/luna-games?game=golf"),
    ("LunaDefender", "🚀 *LUNA DEFENDER*", "https://frg-fight-club.vercel.app/api/luna-games?game=defender"),
    ("LunaTower", "🏗 *LUNA TOWER*", "https://frg-fight-club.vercel.app/api/luna-games?game=tower"),
    ("LunaSnake", "🐍 *LUNA SNAKE*", "https://frg-fight-club.vercel.app/api/luna-games?game=snake"),
    ("LunaFlap", "🚀 *LUNA FLAP*", "https://frg-fight-club.vercel.app/api/luna-games?game=flap"),
    ("LunaPinball", "🎪 *LUNA PINBALL*", "https://frg-fight-club.vercel.app/api/luna-games?game=pinball"),
    ("LunaRacer", "🏎 *LUNA RACER*", "https://frg-fight-club.vercel.app/api/luna-games?game=racer"),
    ("LunaCannon", "💥 *LUNA CANNON*", "https://frg-fight-club.vercel.app/api/luna-games?game=cannon"),
    ("LunaWhack", "👽 *LUNA WHACK*", "https://frg-fight-club.vercel.app/api/luna-games?game=whack"),
    ("LunaRider", "🏍 *LUNA RIDER*", "https://frg-fight-club.vercel.app/api/luna-games?game=rider"),
    ("LunaPool", "🎱 *LUNA POOL*", "https://frg-fight-club.vercel.app/api/luna-games?game=pool"),
    ("ZOMBIEDEFENSE", "🧟 *ZOMBIE DEFENSE*", "https://frg-fight-club.vercel.app/api/luna-games?game=zombie"),
    ("LunaBreakout", "🧱 *LUNA BREAKOUT*", "https://frg-fight-club.vercel.app/api/luna-games?game=breakout"),
    ("LUNACLIMB", "🧗 *LUNA CLIMB*", "https://frg-fight-club.vercel.app/api/luna-games?game=climb"),
)

async def _fetch_board(url):
    try:
        async with httpx.AsyncClient(timeout=6) as client:
            r = await client.get(url)
            if r.status_code == 200:
                return r.json()
    except Exception as e:
        print(f"board fetch failed {url}: {e}")
    return None

def _md_escape(text):
    return re.sub(r"([_*`\[])", r"\\\1", str(text))

async def game_top5_text():
    # Compact one-line-per-game boards (owner asked for a shorter picker
    # post Oct 26): title + top 3 on a single line, no blank separators.
    lines = ["🏆 *Leaderboards — Top 3*"]
    for _short, title, api in GAME_BOARD_APIS:
        board = await _fetch_board(api)
        if board is None:
            lines.append(f"{title} — leaderboard unavailable right now")
            continue
        rows = (board.get("all") or [])[:3]
        if not rows:
            lines.append(f"{title} — no scores yet")
        else:
            tops = " · ".join(
                f"{_md_escape(row.get('name', 'Player'))} {int(row.get('score', 0)):,}"
                for row in rows)
            lines.append(f"{title} — {tops}")
    return "\n".join(lines)

async def on_games(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat is not None and chat.type == "private":
        _btns = [InlineKeyboardButton(label, web_app=WebAppInfo(url=_url))
                 for _short, label, _url in TELEGRAM_GAMES]
        rows = [_btns[i:i + 2] for i in range(0, len(_btns), 2)]
        await update.effective_message.reply_text(GAMES_TEXT, parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(rows))
        return

    # Groups: ONE picker post, never a flood of game cards. The message
    # carries every game's Top 5 and one button per game; a member taps
    # the game they want and only that game's card posts (on_pick_callback).
    _pick = [InlineKeyboardButton(label, callback_data=f"pick:{short_name}")
             for short_name, label, _url in TELEGRAM_GAMES]
    rows = [_pick[i:i + 2] for i in range(0, len(_pick), 2)]
    text = "🎮 *Luna Classic games*\n\n" + await game_top5_text() + "\n\n👇 *Pick a game* — tap one and only that game posts."
    await update.effective_message.reply_text(text, parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(rows))

async def on_pick_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """A member picked one game in a group: post only that game's card."""
    q = update.callback_query
    if q is None or not q.data:
        return
    short_name = q.data.split(":", 1)[1] if ":" in q.data else ""
    # Incoming callback data is matched case-insensitively, but send_game
    # must get the short name exactly as registered in BotFather (Telegram
    # treats game short names as case-sensitive), so the entry carries the
    # canonical TELEGRAM_GAMES spelling through.
    entry = {s.lower(): (s, label, url) for s, label, url in TELEGRAM_GAMES}.get(short_name.lower())
    if not entry:
        print(f"pick callback with unknown game: data={q.data!r}")
        await q.answer(text="That game isn't available.", show_alert=True)
        return
    short_name, label, url = entry
    chat_id = q.message.chat.id if q.message is not None and q.message.chat is not None else None
    # Forum groups: the picker lives in a topic — carry its thread id through
    # so the game card posts in the SAME topic, not the group's General area.
    thread_id = getattr(q.message, "message_thread_id", None) if q.message is not None else None
    thread_kw = {"message_thread_id": thread_id} if thread_id else {}
    try:
        await ctx.bot.send_game(chat_id=chat_id, game_short_name=short_name, **thread_kw)
        await q.answer()
    except Exception as e:
        print(f"pick send_game {short_name} failed: {e}")
        await q.answer(text="Couldn't post that game card — sending its link instead.")
        rows = [[InlineKeyboardButton(label, url=url)]]
        await ctx.bot.send_message(chat_id=chat_id, text="🎮 *Luna Classic games*",
            parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(rows), **thread_kw)

async def on_game_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Telegram asks for the real game URL after a player taps Play."""
    q = update.callback_query
    if q is None or not q.game_short_name:
        return
    url = GAME_URL_BY_SHORT_NAME_CI.get(q.game_short_name.lower())
    print(f"game callback: short_name={q.game_short_name!r} -> {'ok' if url else 'UNMAPPED'}")
    if url:
        await q.answer(url=url)
    else:
        await q.answer(text="That game isn't available.", show_alert=True)

async def on_inline_query(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Let people share a native game card by typing @Luncassistantbot."""
    iq = update.inline_query
    if iq is None:
        return
    needle = (iq.query or "").strip().lower()
    results = []
    for short_name, label, _ in TELEGRAM_GAMES:
        haystack = f"{short_name} {label.lower()}"
        if not needle or needle in haystack:
            results.append(InlineQueryResultGame(id=short_name, game_short_name=short_name))
    await iq.answer(results, cache_time=30, is_personal=False)

async def on_safety(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(SAFETY_TEXT, parse_mode=ParseMode.MARKDOWN)

PRIVACY_TEXT = (
    "🔒 *Privacy & security — what this bot does*\n\n"
    "• *It cannot move funds.* The bot has no wallet, no private keys, and no signing or sending code anywhere. Commands are read-only lookups and settings toggles — plus, only in groups that opted into protection (below), basic moderation actions.\n\n"
    "• *What it logs:* in groups, message text is kept for 7 days so /summary and /catchup can work, then deleted automatically. Your rank counts the days you chat — commands don't count. For the owner's usage stats it also keeps bare counts: chat and user IDs with first/last-seen times and daily totals (commands, messages, button taps) — no message text and no names in those stats, and only the owner can see them.\n\n"
    "• *What the AI sees:* only when someone uses an AI feature (/ask, /summary, mentions, DM summaries). Then the AI service (Groq) receives the message text and usernames needed for that one answer. Simple commands (/price, /validators, …) send nothing anywhere.\n\n"
    "• *Your group's controls:* group admins run this group — including AI on/off (/aioff, /aion), alert settings, and notification choices. Usage stats are owner-only.\n\n"
    "• *The limits:* everyone gets 1 AI question a day (a rank the owner sets by hand for a specific person can raise that person's own cap), moderators can AI-ban an abusive account from AI features only (simple commands keep working), and a hard daily token budget (200,000/day) means the AI quota can't be drained by spam — the worst case is AI pausing until midnight UTC.\n\n"
    "• *Group protection (opt-in):* in groups whose admins registered with /protect and the owner approved, new joiners pass a short safety check before they can post, accounts on the network's global scam-ban list are removed on sight, and a member whose first message contains a link is removed. Moderators can also mute members, keep a word blacklist, trigger anti-raid lockdowns during join surges, and switch on timed safety reminders. Protected-group admins, owner-appointed elevated users, and the owner control the ban list — with rails on that power: every global ban is written to a permanent moderation log, the owner is alerted instantly with a one-tap undo, non-owner moderators are limited to 5 global bans a day, and only the owner can global-ban an elevated user or another protected group's admin. Automatic anti-spam also mutes message flooding, flags the same long message posted across protected groups, and starts brand-new-looking accounts text-only for 24 hours; banned users can appeal to the owner once a day with /appeal.\n\n"
    "• *Don't take our word for it:* the bot's code is public — read exactly what it does: github.com/lunc-projects/lunc-assistant-bot")

async def on_privacy(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(PRIVACY_TEXT, parse_mode=ParseMode.MARKDOWN)

async def _ai_toggle(update: Update, ctx: ContextTypes.DEFAULT_TYPE, on: bool):
    chat = update.effective_chat
    if chat.type == "private":
        await update.effective_message.reply_text("This switch is for groups — in DM, the daily limit applies (1 AI question a day for everyone)."); return
    if not await _can_change(update, ctx):
        await update.effective_message.reply_text("Only group admins can change this group's AI setting."); return
    store.set_ai_enabled(chat.id, on)
    await update.effective_message.reply_text(
        "🤖 AI is ON for this group (daily limits still apply)." if on
        else "🔒 AI is OFF for this group — no AI calls will be made here. Simple commands still work. An admin can turn it back on with /aion.")

async def on_aion(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _ai_toggle(update, ctx, True)

async def on_aioff(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _ai_toggle(update, ctx, False)

# --- Group protection (Phase 1 moderation, 2026-10-25) ---
# Opt-in, owner-approved scam protection for Luna Classic groups,
# modeled on Cosmobot's setup: groups register (owner approves),
# new joiners pass a DM captcha gate, a scammer banned in one
# protected group is banned in all of them, and a first message
# containing a link gets the sender removed. The bot needs admin
# (restrict + delete) in each protected group. Still no wallet,
# no keys, and no fund-moving code anywhere in this bot.

CAPTCHA_MINUTES = 10
CAPTCHA_MAX_STRIKES = 3   # wrong safety-check answers before removal (rejoin + retry allowed)
GBAN_DAILY_LIMIT_NONOWNER = 5  # global bans per UTC day for non-owner moderators (owner: no limit)

# Security round 2 (2026-10-25): automatic anti-spam for protected
# groups — flood control, cross-group repeat detection, fresh-account
# holds. All state is in-memory except the fresh holds (they must
# survive the 24h they span, so they live in the store).
FLOOD_WINDOW = 10          # seconds
FLOOD_MAX = 6              # messages allowed inside the window; the 7th trips
FLOOD_MUTE_MINUTES = 10    # first flood
FLOOD_MUTE2_MINUTES = 60   # repeat flood within the hour
FLOOD_TIMES = {}           # (chat_id, user_id) -> [ts]
FLOOD_OFFENSES = {}        # (chat_id, user_id) -> [count, last_ts]
REPEAT_WINDOW = 900        # same long message in 2+ protected chats within 15 min
REPEAT_SEEN = {}           # fingerprint -> {"chats": {chat_id: ts}, "ts": first_ts}
REPEAT_MUTE_MINUTES = 30
FRESH_HOLD_HOURS = 24
TEXT_ONLY_PERMS = ChatPermissions(can_send_messages=True, can_invite_users=True)
FULL_PERMS = ChatPermissions(
    can_send_messages=True, can_send_audios=True, can_send_documents=True,
    can_send_photos=True, can_send_videos=True, can_send_video_notes=True,
    can_send_voice_notes=True, can_send_polls=True, can_send_other_messages=True,
    can_add_web_page_previews=True, can_invite_users=True)
NO_PERMS = ChatPermissions()
QUIZ = {}  # user_id -> {"chat_id", "items", "idx"}; in-memory only — the pending row + deadline persist in the store
LINK_RE = re.compile(r"(https?://|www\.|t\.me/)", re.I)

# Phase 2 (2026-10-25): anti-raid + timed anti-scam alerts.
RAID_WINDOW = 60        # seconds
RAID_COUNT = 10         # joins inside the window that trigger a lockdown
RAID_MINUTES = 10       # lockdown length
JOIN_TIMES = {}         # chat_id -> [join timestamps] (in-memory; raids are real-time events)
RAID_UNTIL = {}         # chat_id -> lockdown end ts (in-memory)
SCAM_ALERT_EVERY_HOURS = 6
SCAM_ALERTS = [
    "⚠️ Safety reminder: no admin will EVER DM you first or ask for your seed phrase. Anyone who does is a scammer — block and report them.",
    "⚠️ Safety reminder: there are no LUNC-doubling giveaways. If you have to send crypto first to 'unlock' a prize, it's a scam — every time.",
    "⚠️ Safety reminder: only trust links posted in this chat by its admins. Fake airdrop and 'verify your wallet' sites are built to drain wallets.",
]

def _is_owner(user_id):
    return OWNER_ID is not None and user_id == OWNER_ID

async def _is_group_admin(ctx, chat_id, user_id):
    try:
        m = await ctx.bot.get_chat_member(chat_id, user_id)
        return m.status in ("administrator", "creator")
    except Exception:
        return False

async def _can_moderate(update, ctx):
    uid = update.effective_user.id
    if _is_owner(uid) or store.is_elevated(uid):
        return True
    chat = update.effective_chat
    if chat.type in ("group", "supergroup") and store.mod_is_protected(chat.id):
        return await _is_group_admin(ctx, chat.id, uid)
    return False

async def _owner_only(update):
    if _is_owner(update.effective_user.id):
        return True
    await update.effective_message.reply_text("Owner only.")
    return False

async def on_protect(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        await update.effective_message.reply_text("Run /protect inside the group you want protected."); return
    if not await _can_change(update, ctx):
        await update.effective_message.reply_text("Only group admins can request protection."); return
    row = store.mod_group(chat.id)
    if row is not None and row["approved"]:
        await update.effective_message.reply_text("🛡 This group is already protected."); return
    store.mod_request_group(chat.id, chat.title or "", update.effective_user.id)
    missing = []
    try:
        me = await ctx.bot.get_chat_member(chat.id, ctx.bot.id)
        if me.status != "administrator":
            missing.append("make the bot an admin")
        else:
            if not getattr(me, "can_restrict_members", False): missing.append("'restrict members' permission")
            if not getattr(me, "can_delete_messages", False): missing.append("'delete messages' permission")
    except Exception:
        missing.append("(couldn't verify the bot's admin rights)")
    note = ("\n⚠️ Still needed for the gate to work: " + ", ".join(missing) + ".") if missing else ""
    await update.effective_message.reply_text("🛡 Protection requested — the bot owner has been notified for approval." + note)
    if OWNER_ID:
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Approve", callback_data=f"mod:approve:{chat.id}"),
            InlineKeyboardButton("❌ Deny", callback_data=f"mod:deny:{chat.id}")]])
        try:
            await ctx.bot.send_message(OWNER_ID, f"🛡 Protection request: {chat.title} (chat id {chat.id}), requested by user {update.effective_user.id}.\nTap a button — or use /approve {chat.id} · /deny {chat.id}", reply_markup=kb)
        except Exception:
            pass

async def on_unprotect(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        await update.effective_message.reply_text("Run /unprotect inside the group."); return
    if not (_is_owner(update.effective_user.id) or await _can_change(update, ctx)):
        await update.effective_message.reply_text("Only group admins (or the owner) can remove protection."); return
    if store.mod_remove_group(chat.id):
        await update.effective_message.reply_text("Protection removed — this group is no longer in the network.")
    else:
        await update.effective_message.reply_text("This group wasn't registered.")

async def on_approve(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _owner_only(update): return
    if not ctx.args:
        pend = store.pending_groups()
        if len(pend) == 1:
            chat_id = pend[0]["chat_id"]
        elif not pend:
            await update.effective_message.reply_text("No groups are waiting for approval."); return
        else:
            await update.effective_message.reply_text("More than one group is waiting — see them with /groups, then /approve <chat_id>."); return
    else:
        try: chat_id = int(ctx.args[0])
        except ValueError:
            await update.effective_message.reply_text("Chat id must be a number."); return
    if store.mod_approve_group(chat_id):
        await update.effective_message.reply_text(f"✅ Group {chat_id} approved — protection is ON.")
        try: await ctx.bot.send_message(chat_id, "🛡 Protection is ON for this group: new joiners pass a short safety check before they can post, known scammers are removed automatically, and a first message containing a link gets the sender removed.")
        except Exception: pass
    else:
        await update.effective_message.reply_text("No pending or registered group with that id.")

async def on_deny(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _owner_only(update): return
    if not ctx.args:
        await update.effective_message.reply_text("Usage: /deny <chat_id>"); return
    try: chat_id = int(ctx.args[0])
    except ValueError:
        await update.effective_message.reply_text("Chat id must be a number."); return
    if store.mod_remove_group(chat_id):
        await update.effective_message.reply_text(f"Group {chat_id} removed from the list.")
    else:
        await update.effective_message.reply_text("No group with that id.")

async def on_groups(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _owner_only(update): return
    rows = store.mod_groups(approved_only=False)
    if not rows:
        await update.effective_message.reply_text("No groups registered or pending."); return
    lines = ["*Protection network*"]
    for r in rows:
        lines.append(f"{'🛡' if r['approved'] else '⏳ pending'} {r['title'] or '(no title)'} — chat id {r['chat_id']}")
    await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)

async def _apply_gban(ctx, target_id, ban):
    ok = fail = 0
    for g in store.mod_groups():
        try:
            if ban:
                await ctx.bot.ban_chat_member(g["chat_id"], target_id)
            else:
                await ctx.bot.unban_chat_member(g["chat_id"], target_id, only_if_banned=True)
            ok += 1
        except Exception:
            fail += 1
    return ok, fail

def _mod_target(update, ctx):
    """Reply-target wins; else a numeric first argument."""
    if update.message.reply_to_message and update.message.reply_to_message.from_user:
        return update.message.reply_to_message.from_user.id, " ".join(ctx.args or [])
    if ctx.args:
        try: return int(ctx.args[0]), " ".join(ctx.args[1:])
        except ValueError: return None, ""
    return None, ""

def _utc_day_start():
    now = datetime.datetime.now(datetime.timezone.utc)
    return int(now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())

async def _owner_mod_alert(ctx, text, undo_user_id=None):
    """Instant owner DM for a moderator action, with a one-tap undo
    button for global bans. The owner is the backstop on ban abuse."""
    if not OWNER_ID:
        return
    kb = None
    if undo_user_id:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(
            "↩️ Undo this global ban", callback_data=f"modundo:{undo_user_id}")]])
    try:
        await ctx.bot.send_message(OWNER_ID, text, reply_markup=kb)
    except Exception:
        pass

async def on_gban(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _can_moderate(update, ctx):
        await update.effective_message.reply_text("Only the owner, elevated users, or admins of a protected group can do this."); return
    actor = update.effective_user.id
    target, reason = _mod_target(update, ctx)
    if not target:
        await update.effective_message.reply_text("Usage: reply to the scammer's message with /gban [reason], or /gban <user_id> [reason]."); return
    if _is_owner(target):
        await update.effective_message.reply_text("That user can't be banned."); return
    if target == actor:
        await update.effective_message.reply_text("You can't ban yourself."); return
    if not _is_owner(actor):
        # Anti-abuse rails (2026-10-25): moderators can't ban up the
        # chain, and nobody gets to mass-ban — the owner is alerted
        # with an undo button for every one of these (below).
        if store.is_elevated(target):
            await update.effective_message.reply_text("🚫 Only the owner can globally ban an elevated user."); return
        for g in store.mod_groups():
            if await _is_group_admin(ctx, g["chat_id"], target):
                await update.effective_message.reply_text("🚫 That user is an admin in a protected group — only the owner can globally ban them."); return
        if store.mod_action_count(actor, "gban", _utc_day_start()) >= GBAN_DAILY_LIMIT_NONOWNER:
            await update.effective_message.reply_text(f"🚫 You've hit today's limit of {GBAN_DAILY_LIMIT_NONOWNER} global bans for non-owner moderators — it resets at midnight UTC. The owner has no limit."); return
    store.gban_add(target, reason, actor)
    store.mod_log_add(actor, "gban", target, update.effective_chat.id, reason)
    ok, fail = await _apply_gban(ctx, target, True)
    await update.effective_message.reply_text(f"🚫 User {target} is now globally banned — removed from {ok} protected group(s)" + (f" ({fail} failed — the bot may lack admin rights there)" if fail else "") + ".")
    if not _is_owner(actor):
        await _owner_mod_alert(ctx,
            f"🚫 Global ban by moderator {actor}\nUser: {target}\nReason: {reason or '(none given)'}\nFrom chat: {update.effective_chat.id}\nRemoved from {ok} group(s)" + (f" ({fail} failed)" if fail else "") + "\nWrong call? Undo it:",
            undo_user_id=target)

async def on_gunban(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _can_moderate(update, ctx):
        await update.effective_message.reply_text("Only the owner, elevated users, or admins of a protected group can do this."); return
    actor = update.effective_user.id
    if not ctx.args:
        await update.effective_message.reply_text("Usage: /gunban <user_id>"); return
    try: target = int(ctx.args[0])
    except ValueError:
        await update.effective_message.reply_text("User id must be a number."); return
    row = store.gban_get(target)
    if row is None:
        await update.effective_message.reply_text("That user isn't on the global ban list."); return
    if not _is_owner(actor) and row["banned_by"] == OWNER_ID:
        await update.effective_message.reply_text("🚫 Only the owner can lift a global ban the owner placed."); return
    store.gban_remove(target)
    store.mod_log_add(actor, "gunban", target, update.effective_chat.id, "")
    ok, fail = await _apply_gban(ctx, target, False)
    await update.effective_message.reply_text(f"✅ User {target} removed from the global ban list and unbanned in {ok} group(s)" + (f" ({fail} failed)" if fail else "") + ".")
    if not _is_owner(actor):
        await _owner_mod_alert(ctx, f"✅ Global ban LIFTED by moderator {actor}\nUser: {target}\nUnbanned in {ok} group(s)" + (f" ({fail} failed)" if fail else "") + ".")

async def on_gbans(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _can_moderate(update, ctx):
        await update.effective_message.reply_text("Only the owner, elevated users, or admins of a protected group can see this."); return
    rows = store.gban_all()
    if not rows:
        await update.effective_message.reply_text("The global ban list is empty."); return
    lines = [f"*Global ban list ({len(rows)})*"]
    for r in rows[:30]:
        lines.append(f"• {r['user_id']}" + (f" — {r['reason']}" if r["reason"] else "") + f" (by {r['banned_by']})")
    if len(rows) > 30: lines.append(f"…and {len(rows) - 30} more")
    await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)

async def on_aiban(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """AI ban: blocks ALL AI features for one user (every chat + DM).
    They keep chatting and keep every simple command — only the token-
    spending features stop. The light-touch answer to AI abuse."""
    if not await _can_moderate(update, ctx):
        await update.effective_message.reply_text("Only the owner, elevated users, or admins of a protected group can do this."); return
    actor = update.effective_user.id
    target, reason = _mod_target(update, ctx)
    if not target:
        await update.effective_message.reply_text("Usage: reply to their message with /aiban [reason], or /aiban <user_id> [reason]."); return
    if _is_owner(target):
        await update.effective_message.reply_text("That user can't be AI-banned."); return
    if target == actor:
        await update.effective_message.reply_text("You can't AI-ban yourself."); return
    if not _is_owner(actor) and store.is_elevated(target):
        await update.effective_message.reply_text("🚫 Only the owner can AI-ban an elevated user."); return
    store.ai_ban_add(target, reason, actor)
    store.mod_log_add(actor, "aiban", target, update.effective_chat.id, reason)
    await update.effective_message.reply_text(f"🤖🚫 User {target} is AI-banned — no /ask, summaries, or AI answers for them anywhere. Simple commands still work. Lift it with /aiunban {target}.")
    if not _is_owner(actor):
        await _owner_mod_alert(ctx, f"🤖🚫 AI ban by moderator {actor}\nUser: {target}\nReason: {reason or '(none given)'}\nFrom chat: {update.effective_chat.id}\nLift it any time with /aiunban {target}.")

async def on_aiunban(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _can_moderate(update, ctx):
        await update.effective_message.reply_text("Only the owner, elevated users, or admins of a protected group can do this."); return
    actor = update.effective_user.id
    if not ctx.args:
        await update.effective_message.reply_text("Usage: /aiunban <user_id>"); return
    try: target = int(ctx.args[0])
    except ValueError:
        await update.effective_message.reply_text("User id must be a number."); return
    row = store.ai_ban_get(target)
    if row is None:
        await update.effective_message.reply_text("That user isn't AI-banned."); return
    if not _is_owner(actor) and row["banned_by"] == OWNER_ID:
        await update.effective_message.reply_text("🚫 Only the owner can lift an AI ban the owner placed."); return
    store.ai_ban_remove(target)
    store.mod_log_add(actor, "aiunban", target, update.effective_chat.id, "")
    await update.effective_message.reply_text(f"✅ AI ban lifted for user {target} — AI features work for them again (rank caps still apply).")

async def on_aibans(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _can_moderate(update, ctx):
        await update.effective_message.reply_text("Only the owner, elevated users, or admins of a protected group can see this."); return
    rows = store.ai_ban_all()
    if not rows:
        await update.effective_message.reply_text("No AI bans right now."); return
    lines = [f"*AI ban list ({len(rows)})*"]
    for r in rows[:30]:
        lines.append(f"• {r['user_id']}" + (f" — {r['reason']}" if r["reason"] else "") + f" (by {r['banned_by']})")
    if len(rows) > 30: lines.append(f"…and {len(rows) - 30} more")
    await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)

async def on_modlog(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _owner_only(update): return
    rows = store.mod_log_recent(15)
    if not rows:
        await update.effective_message.reply_text("The moderation log is empty."); return
    lines = ["*Moderation log — latest first*"]
    for r in rows:
        when = datetime.datetime.fromtimestamp(r["ts"], datetime.timezone.utc).strftime("%b %d %H:%M UTC")
        lines.append(f"• {when} — {r['action']}" + (f": user {r['target']}" if r["target"] else "") + f" by {r['actor'] or 'auto'}" + (f" — {r['detail']}" if r["detail"] else ""))
    await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)

async def on_modundo_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not _is_owner(q.from_user.id):
        await q.answer("Owner only.", show_alert=True); return
    try: target = int((q.data or "").split(":")[1])
    except Exception:
        await q.answer("Bad button."); return
    if not store.gban_remove(target):
        await q.answer("That ban is already gone.", show_alert=True); return
    store.mod_log_add(q.from_user.id, "gunban", target, None, "owner undo button")
    ok, fail = await _apply_gban(ctx, target, False)
    await q.answer("Ban lifted ✅")
    try: await q.edit_message_text((q.message.text or "") + f"\n\n↩️ Undone by you — user {target} unbanned in {ok} group(s)" + (f" ({fail} failed)" if fail else "") + ".")
    except Exception: pass

async def on_aiundo_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not _is_owner(q.from_user.id):
        await q.answer("Owner only.", show_alert=True); return
    try: target = int((q.data or "").split(":")[1])
    except Exception:
        await q.answer("Bad button."); return
    if not store.ai_ban_remove(target):
        await q.answer("That AI ban is already gone.", show_alert=True); return
    store.mod_log_add(q.from_user.id, "aiunban", target, None, "owner button (appeal/alert)")
    await q.answer("AI ban lifted ✅")
    try: await q.edit_message_text((q.message.text or "") + f"\n\n↩️ Undone by you — AI ban lifted for user {target}.")
    except Exception: pass

async def on_appeal(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Ban appeal: a user on the global ban list or AI ban list can ask
    the owner for a review, in DM, at most once a day. The owner gets
    the ban record plus one-tap lift buttons."""
    chat, user = update.effective_chat, update.effective_user
    if chat.type != "private":
        await update.effective_message.reply_text("Appeals are private — DM me and send /appeal there."); return
    g = store.gban_get(user.id)
    a = store.ai_ban_get(user.id)
    if not g and not a:
        await update.effective_message.reply_text("You have no ban on record with me — nothing to appeal. (This covers only this bot's global ban list and AI ban list.)"); return
    last = store.appeal_last(user.id)
    if last and int(time.time()) - last["ts"] < 86400:
        await update.effective_message.reply_text("You've already appealed in the last 24 hours — the owner has it. One appeal a day keeps it readable."); return
    text = " ".join(ctx.args or []).strip()
    kinds = ("global ban" if g else "") + (" + " if g and a else "") + ("AI ban" if a else "")
    store.appeal_record(user.id, kinds)
    store.mod_log_add(user.id, "appeal", user.id, None, kinds)
    await update.effective_message.reply_text("✅ Appeal sent to the owner, with the ban record attached. If they lift it, you'll see the bot working for you again — no need to send more.")
    if OWNER_ID:
        rows = []
        detail = []
        if g:
            rows.append([InlineKeyboardButton("↩️ Lift the global ban", callback_data=f"modundo:{user.id}")])
            detail.append(f"Global ban: {g['reason'] or '(no reason given)'} · placed by {g['banned_by']}")
        if a:
            rows.append([InlineKeyboardButton("↩️ Lift the AI ban", callback_data=f"aiundo:{user.id}")])
            detail.append(f"AI ban: {a['reason'] or '(no reason given)'} · placed by {a['banned_by']}")
        try: await ctx.bot.send_message(OWNER_ID, f"📩 Ban appeal ({kinds})\nUser: {user.id} ({user.full_name})\n" + "\n".join(detail) + f"\nTheir words: {text[:500] if text else '(no message)'}", reply_markup=InlineKeyboardMarkup(rows) if rows else None)
        except Exception: pass

async def on_elevate(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _owner_only(update): return
    target = None
    if update.message.reply_to_message and update.message.reply_to_message.from_user:
        target = update.message.reply_to_message.from_user.id
    elif ctx.args:
        try: target = int(ctx.args[0])
        except ValueError:
            await update.effective_message.reply_text("User id must be a number."); return
    if not target:
        await update.effective_message.reply_text("Usage: reply to the person's message with /elevate, or /elevate <user_id>."); return
    store.elevated_add(target, update.effective_user.id)
    store.mod_log_add(update.effective_user.id, "elevate", target, update.effective_chat.id, "")
    await update.effective_message.reply_text(f"✅ User {target} is now an elevated user (can /gban and /gunban across every protected group).")

async def on_unelevate(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _owner_only(update): return
    if not ctx.args:
        await update.effective_message.reply_text("Usage: /unelevate <user_id>"); return
    try: target = int(ctx.args[0])
    except ValueError:
        await update.effective_message.reply_text("User id must be a number."); return
    if store.elevated_remove(target):
        store.mod_log_add(update.effective_user.id, "unelevate", target, update.effective_chat.id, "")
        await update.effective_message.reply_text(f"User {target} is no longer elevated.")
    else:
        await update.effective_message.reply_text("That user wasn't elevated.")

async def on_elevated(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _owner_only(update): return
    rows = store.elevated_all()
    if not rows:
        await update.effective_message.reply_text("No elevated users yet. Add one with /elevate <user_id>."); return
    await update.effective_message.reply_text("Elevated users: " + ", ".join(str(r["user_id"]) for r in rows))

async def on_new_members(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"): return
    if not store.mod_is_protected(chat.id):
        # Unprotected groups: just show the welcome note, if one is set.
        w = store.get_setting(chat.id, "welcome_text")
        if w:
            names = ", ".join(m.first_name for m in update.message.new_chat_members if not m.is_bot)
            if names:
                try: await ctx.bot.send_message(chat.id, f"👋 Welcome, {names}!\n\n{w}")
                except Exception: pass
        return
    # Anti-raid: a surge of joins inside a short window locks the group
    # down for a while — during lockdown every new joiner is removed.
    now = int(time.time())
    times = [t for t in JOIN_TIMES.get(chat.id, []) if now - t < RAID_WINDOW]
    times += [now] * len(update.message.new_chat_members)
    JOIN_TIMES[chat.id] = times
    raid = RAID_UNTIL.get(chat.id, 0) > now
    if not raid and len(times) >= RAID_COUNT:
        raid = True
        RAID_UNTIL[chat.id] = now + RAID_MINUTES * 60
        try: await ctx.bot.send_message(chat.id, f"🚨 Anti-raid: a surge of new joins was detected, so lockdown is ON for {RAID_MINUTES} minutes — new joiners are removed on sight. An admin can lift it early with /raid off.")
        except Exception: pass
    for m in update.message.new_chat_members:
        if m.is_bot: continue
        if _is_owner(m.id): continue
        if store.gban_get(m.id):
            try: await ctx.bot.ban_chat_member(chat.id, m.id)
            except Exception: pass
            continue
        if raid:
            try:
                await ctx.bot.ban_chat_member(chat.id, m.id)
                await ctx.bot.unban_chat_member(chat.id, m.id, only_if_banned=True)
            except Exception: pass
            continue
        if store.member_is_verified(chat.id, m.id):
            fh = store.fresh_get(chat.id, m.id)
            if fh and fh["until_ts"] > now:
                try: await ctx.bot.restrict_chat_member(chat.id, m.id, permissions=TEXT_ONLY_PERMS)
                except Exception: pass
            continue
        if await _is_group_admin(ctx, chat.id, m.id):
            store.member_verify(chat.id, m.id); continue
        try:
            await ctx.bot.restrict_chat_member(chat.id, m.id, permissions=NO_PERMS)
        except Exception as e:
            # NEVER fail silently: a gate that can't hold a joiner is a
            # live security hole. Warn the group (an admin must grant
            # the 'Ban users' permission) and alert the owner through
            # the throttled issue-alert channel.
            try: await ctx.bot.send_message(chat.id, "⚠️ I couldn't hold a new member for the safety check — I need the 'Ban users' admin permission in this group. Until an admin grants it, new joiners here are NOT being checked.")
            except Exception: pass
            await _alert_owner(ctx.bot, f"safety gate in chat {chat.id}", e)
            continue
        store.captcha_start(chat.id, m.id, int(time.time()) + CAPTCHA_MINUTES * 60)
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Start the safety check", url=f"https://t.me/{ctx.bot.username}?start=captcha")]])
        w = store.get_setting(chat.id, "welcome_text")
        try:
            await ctx.bot.send_message(chat.id, f"👋 Welcome, {m.first_name}! This group is protected against scams. To start chatting, tap the button, then Start in my DM and pass a short safety check within {CAPTCHA_MINUTES} minutes." + (f"\n\n{w}" if w else ""), reply_markup=kb)
        except Exception: pass

async def on_left_member(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    left = update.message.left_chat_member
    if left:
        store.captcha_clear(update.effective_chat.id, left.id)
        store.captcha_strikes_clear(update.effective_chat.id, left.id)
        QUIZ.pop(left.id, None)

async def _start_quiz(update, ctx, pend):
    sess = {"chat_id": pend["chat_id"], "items": modquiz.build_quiz(), "idx": 0}
    QUIZ[update.effective_user.id] = sess
    g = store.mod_group(pend["chat_id"])
    title = g["title"] if g else "the group"
    await update.effective_message.reply_text(f"🛡 Quick check for *{title}* — {len(sess['items'])} simple taps to prove you're a real person. Get them all right to unlock chatting.", parse_mode=ParseMode.MARKDOWN)
    await _quiz_send(update.effective_message.reply_text, sess)

async def _quiz_send(reply_fn, sess):
    item = sess["items"][sess["idx"]]
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(opt, callback_data=f"cap:{sess['idx']}:{i}")] for i, opt in enumerate(item["options"])])
    await reply_fn(f"Question {sess['idx'] + 1} of {len(sess['items'])}\n\n{item['prompt']}", reply_markup=kb)

async def on_captcha_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    sess = QUIZ.get(uid)
    if not sess:
        await q.answer("This check has expired — rejoin the group and tap the button there to start again.", show_alert=True); return
    try:
        _, idx_s, choice_s = q.data.split(":")
        idx, choice = int(idx_s), int(choice_s)
    except Exception:
        await q.answer("Out of date — use the latest question."); return
    if idx != sess["idx"]:
        await q.answer("Out of date — use the latest question."); return
    if store.captcha_get(sess["chat_id"], uid) is None:
        QUIZ.pop(uid, None)
        await q.answer("This check has expired — rejoin the group and tap the button there to start again.", show_alert=True); return
    item = sess["items"][idx]
    if choice != item["answer"]:
        QUIZ.pop(uid, None)
        strikes = store.captcha_strike_add(sess["chat_id"], uid)
        if strikes >= CAPTCHA_MAX_STRIKES:
            store.captcha_strikes_clear(sess["chat_id"], uid)
            store.captcha_clear(sess["chat_id"], uid)
            try:
                await ctx.bot.ban_chat_member(sess["chat_id"], uid)
                await ctx.bot.unban_chat_member(sess["chat_id"], uid, only_if_banned=True)
            except Exception: pass
            await q.answer("❌ Too many wrong answers.", show_alert=True)
            try: await q.edit_message_text(f"❌ That's {CAPTCHA_MAX_STRIKES} wrong answers, so you've been removed from the group for now. You can rejoin and try the check again — read each question carefully; the safe answers are common sense.")
            except Exception: pass
            return
        await q.answer("❌ That's not the safe answer.", show_alert=True)
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("↻ Try the check again", url=f"https://t.me/{ctx.bot.username}?start=captcha")]])
        try: await q.edit_message_text(f"❌ That answer isn't right, so this attempt ends here. Tap below and try again before your time in the group runs out.\n\n⚠️ Careful: {CAPTCHA_MAX_STRIKES - strikes} wrong answer(s) left — at {CAPTCHA_MAX_STRIKES} you're removed (you can rejoin and try again).", reply_markup=kb)
        except Exception: pass
        return
    sess["idx"] += 1
    if sess["idx"] < len(sess["items"]):
        await q.answer("✅ Correct")
        try: await q.edit_message_text(f"✅ Correct — {sess['idx']} of {len(sess['items'])} done.")
        except Exception: pass
        await _quiz_send(q.message.reply_text, sess)
        return
    chat_id = sess["chat_id"]
    QUIZ.pop(uid, None)
    store.captcha_clear(chat_id, uid)
    store.captcha_strikes_clear(chat_id, uid)
    store.member_verify(chat_id, uid)
    # Fresh-account hold: no username AND no profile photo looks like a
    # throwaway account. They can chat right away, but text-only (no
    # media, no link previews — the scam vectors) for the first 24h;
    # job_fresh_sweep lifts it automatically. If the photo check can't
    # be made, we don't hold on a guess.
    fresh = False
    if not q.from_user.username:
        try:
            photos = await ctx.bot.get_user_profile_photos(uid, limit=1)
            fresh = seclogic.fresh_looking(False, photos.total_count)
        except Exception:
            fresh = False
    if fresh:
        store.fresh_add(chat_id, uid, int(time.time()) + FRESH_HOLD_HOURS * 3600)
        try: await ctx.bot.restrict_chat_member(chat_id, uid, permissions=TEXT_ONLY_PERMS)
        except Exception: pass
        await q.answer("✅ You passed!")
        try: await q.edit_message_text("✅ You passed the safety check — you can chat in the group now. One extra for brand-new-looking accounts (no username, no profile photo): you're text-only for the first 24 hours — no photos, videos, or link previews — then full access opens automatically. Stay safe: no real admin will ever DM you asking for a seed phrase or a wallet approval.")
        except Exception: pass
        return
    try: await ctx.bot.restrict_chat_member(chat_id, uid, permissions=FULL_PERMS)
    except Exception: pass
    await q.answer("✅ You passed!")
    try: await q.edit_message_text("✅ You passed the safety check — you can chat in the group now. Stay safe: no real admin will ever DM you asking for a seed phrase or a wallet approval.")
    except Exception: pass

async def job_captcha_sweep(ctx: ContextTypes.DEFAULT_TYPE):
    for row in store.captcha_expired(int(time.time())):
        try:
            await ctx.bot.ban_chat_member(row["chat_id"], row["user_id"])
            await ctx.bot.unban_chat_member(row["chat_id"], row["user_id"], only_if_banned=True)
        except Exception: pass
        store.captcha_clear(row["chat_id"], row["user_id"])
        store.captcha_strikes_clear(row["chat_id"], row["user_id"])
        QUIZ.pop(row["user_id"], None)

async def job_fresh_sweep(ctx: ContextTypes.DEFAULT_TYPE):
    """Lift fresh-account holds as they expire (full permissions back)."""
    for row in store.fresh_due(int(time.time())):
        try: await ctx.bot.restrict_chat_member(row["chat_id"], row["user_id"], permissions=FULL_PERMS)
        except Exception: pass
        store.fresh_remove(row["chat_id"], row["user_id"])

# --- Phase 2 moderation: mute, blacklist, anti-raid, alerts, stats ---

async def on_mute(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        await update.effective_message.reply_text("Use /mute in a group."); return
    if not await _can_moderate(update, ctx):
        await update.effective_message.reply_text("Only the owner, elevated users, or admins of a protected group can do this."); return
    target, rest = _mod_target(update, ctx)
    if not target:
        await update.effective_message.reply_text("Usage: reply to their message with /mute [minutes], or /mute <user_id> [minutes]. Default is 60 minutes."); return
    if _is_owner(target):
        await update.effective_message.reply_text("That user can't be muted."); return
    minutes = 60
    for tok in rest.split():
        try: minutes = int(tok); break
        except ValueError: continue
    minutes = max(1, min(minutes, 43200))
    until = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=minutes)
    try:
        await ctx.bot.restrict_chat_member(chat.id, target, permissions=NO_PERMS, until_date=until)
        await update.effective_message.reply_text(f"🔇 User {target} is muted for {minutes} minute(s).")
    except Exception:
        await update.effective_message.reply_text("Couldn't mute them — the bot may lack admin rights here, or they're an admin.")

async def on_unmute(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        await update.effective_message.reply_text("Use /unmute in a group."); return
    if not await _can_moderate(update, ctx):
        await update.effective_message.reply_text("Only the owner, elevated users, or admins of a protected group can do this."); return
    target, _ = _mod_target(update, ctx)
    if not target:
        await update.effective_message.reply_text("Usage: reply to their message with /unmute, or /unmute <user_id>."); return
    try:
        await ctx.bot.restrict_chat_member(chat.id, target, permissions=FULL_PERMS)
        await update.effective_message.reply_text(f"🔊 User {target} can chat again.")
    except Exception:
        await update.effective_message.reply_text("Couldn't unmute them — the bot may lack admin rights here.")

async def on_blacklist(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not (_is_owner(uid) or store.is_elevated(uid)):
        await update.effective_message.reply_text("Only the owner and elevated users manage the word blacklist."); return
    args = ctx.args or []
    if len(args) >= 2 and args[0].lower() == "add":
        word = args[1].lower().strip()
        if len(word) < 3:
            await update.effective_message.reply_text("Blacklist words need at least 3 characters."); return
        store.blacklist_add(word, uid)
        store.mod_log_add(uid, "blacklist add", None, update.effective_chat.id, word)
        await update.effective_message.reply_text(f"✅ '{word}' is on the blacklist — in protected groups, a message containing it is deleted and the sender removed."); return
    if len(args) >= 2 and args[0].lower() == "remove":
        if store.blacklist_remove(args[1].lower()):
            store.mod_log_add(uid, "blacklist remove", None, update.effective_chat.id, args[1].lower())
            await update.effective_message.reply_text("Removed from the blacklist.")
        else:
            await update.effective_message.reply_text("That word wasn't on the blacklist.")
        return
    words = store.blacklist_all()
    await update.effective_message.reply_text("Word blacklist: " + (", ".join(words) if words else "(empty)") + "\nAdd: /blacklist add <word> · Remove: /blacklist remove <word>")

# --- Per-group phrase filter: delete + 24h mute (2026-10-27) ---
# Command is /muteword (NOT /filter: Rose, the FRG group's existing
# management bot, already owns /filter there — a collision).
# NOT the global blacklist: phrases live in a per-chat setting, apply
# ONLY in that group, and work with or without /protect. A hit deletes
# the message and mutes the sender for 24 hours — never a ban. The
# group's own admins, elevated users, and the owner are exempt
# entirely (their messages are not even deleted), the same way the
# protection rules treat them.
FILTER_KEY = "mute_filter"
FILTER_MUTE_HOURS = 24

def _filter_phrases(chat_id):
    raw = store.get_setting(chat_id, FILTER_KEY)
    if not raw: return []
    try: phrases = json.loads(raw)
    except Exception: return []
    if not isinstance(phrases, list): return []
    return [p for p in phrases if isinstance(p, str) and p]

def _filter_save(chat_id, phrases):
    store.set_setting(chat_id, FILTER_KEY, json.dumps(phrases))

def _filter_match(chat_id, text):
    """First of THIS group's filtered phrases found in text (case-insensitive substring), else None."""
    if not text: return None
    phrases = _filter_phrases(chat_id)
    if not phrases: return None
    low = text.lower()
    return next((p for p in phrases if p in low), None)

async def _can_manage_filter(update, ctx):
    uid = update.effective_user.id
    if _is_owner(uid) or store.is_elevated(uid): return True
    chat = update.effective_chat
    if chat.type in ("group", "supergroup"):
        return await _is_group_admin(ctx, chat.id, uid)
    return False

async def on_muteword(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        await update.effective_message.reply_text("Use /muteword in a group — the phrase filter is set per group."); return
    if not await _can_manage_filter(update, ctx):
        await update.effective_message.reply_text("Only this group's admins, elevated users, or the owner can manage the phrase filter."); return
    args = ctx.args or []
    sub = args[0].lower() if args else ""
    if sub in ("add", "remove") and len(args) >= 2:
        phrase = " ".join(args[1:]).lower().strip()
        phrases = _filter_phrases(chat.id)
        if sub == "add":
            if len(phrase) < 3:
                await update.effective_message.reply_text("Filter phrases need at least 3 characters."); return
            if phrase in phrases:
                await update.effective_message.reply_text(f"'{phrase}' is already on this group's filter."); return
            phrases.append(phrase)
            _filter_save(chat.id, phrases)
            store.mod_log_add(update.effective_user.id, "filter add", None, chat.id, phrase)
            await update.effective_message.reply_text(f"✅ '{phrase}' is on this group's filter — a message containing it is deleted and the sender muted for {FILTER_MUTE_HOURS} hours (this group only)."); return
        if phrase in phrases:
            phrases.remove(phrase)
            _filter_save(chat.id, phrases)
            store.mod_log_add(update.effective_user.id, "filter remove", None, chat.id, phrase)
            await update.effective_message.reply_text(f"Removed '{phrase}' from this group's filter.")
        else:
            await update.effective_message.reply_text("That phrase isn't on this group's filter.")
        return
    phrases = _filter_phrases(chat.id)
    await update.effective_message.reply_text(
        f"🚫 Phrase filter for this group: {'ON — ' + str(len(phrases)) + ' phrase(s)' if phrases else 'OFF (no phrases set)'}\n"
        + (("Phrases: " + ", ".join(phrases) + "\n") if phrases else "")
        + f"A message containing a filtered phrase is deleted and the sender muted for {FILTER_MUTE_HOURS} hours. This group's admins, elevated users, and the owner are exempt.\n"
        + "Add: /muteword add <phrase> · Remove: /muteword remove <phrase> · List: /muteword list")

async def _mute_filter_check(ctx, chat, user, text, msg):
    """Enforce this group's phrase filter on one message/caption/edit.
    Returns True if it fired: message deleted, sender muted 24h, notice
    posted, mod-log written. Callers run it AFTER the global blacklist
    in protected groups, so a message hit by both gets the blacklist's
    delete + remove only — never a double punishment."""
    if not user or user.is_bot: return False
    phrase = _filter_match(chat.id, text)
    if not phrase: return False
    if _is_owner(user.id) or store.is_elevated(user.id): return False
    if await _is_group_admin(ctx, chat.id, user.id): return False
    try: await msg.delete()
    except Exception: pass
    until = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=FILTER_MUTE_HOURS)
    muted = True
    try: await ctx.bot.restrict_chat_member(chat.id, user.id, permissions=NO_PERMS, until_date=until)
    except Exception: muted = False
    store.mod_log_add(0, "filter mute", user.id, chat.id, f"phrase '{phrase}', {FILTER_MUTE_HOURS}h")
    name = user.full_name or str(user.id)
    note = (f"🔇 {name} was muted for {FILTER_MUTE_HOURS} hours — a message containing a filtered phrase ('{phrase}') was removed."
            if muted else
            f"⚠️ A message from {name} containing a filtered phrase ('{phrase}') was removed, but the mute failed — the bot may lack admin rights here.")
    try: await ctx.bot.send_message(chat.id, note)
    except Exception: pass
    return True

async def on_raid(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        await update.effective_message.reply_text("Use /raid in a group."); return
    if not await _can_moderate(update, ctx):
        await update.effective_message.reply_text("Only the owner, elevated users, or admins of a protected group can do this."); return
    arg = (ctx.args or [""])[0].lower()
    if arg == "on":
        RAID_UNTIL[chat.id] = int(time.time()) + RAID_MINUTES * 60
        await update.effective_message.reply_text(f"🚨 Anti-raid lockdown ON for {RAID_MINUTES} minutes — new joiners are removed on sight.")
    elif arg == "off":
        RAID_UNTIL.pop(chat.id, None)
        await update.effective_message.reply_text("Anti-raid lockdown lifted.")
    else:
        active = RAID_UNTIL.get(chat.id, 0) > int(time.time())
        await update.effective_message.reply_text(("🚨 Anti-raid lockdown is ON right now." if active else "Anti-raid lockdown is off (it turns on automatically during a join surge).") + " Usage: /raid on · /raid off")

async def on_scamalerts(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        await update.effective_message.reply_text("Use /scamalerts in a group."); return
    if not store.mod_is_protected(chat.id):
        await update.effective_message.reply_text("This group isn't protected yet — an admin can request it with /protect."); return
    if not await _can_change(update, ctx):
        await update.effective_message.reply_text("Only group admins can change this."); return
    arg = (ctx.args or [""])[0].lower()
    if arg in ("on", "off"):
        store.set_scam_alerts(chat.id, arg == "on")
        await update.effective_message.reply_text(f"⚠️ Timed anti-scam reminders are {arg.upper()} for this group" + (f" (one every ~{SCAM_ALERT_EVERY_HOURS} hours)." if arg == "on" else "."))
    else:
        await update.effective_message.reply_text(f"Timed anti-scam reminders are {'ON' if store.scam_alerts_enabled(chat.id) else 'OFF'} for this group. Usage: /scamalerts on · /scamalerts off")

async def job_scam_alerts(ctx: ContextTypes.DEFAULT_TYPE):
    now = int(time.time())
    for g in store.mod_groups():
        cid = g["chat_id"]
        if not store.scam_alerts_enabled(cid): continue
        if now - store.scam_last(cid) < SCAM_ALERT_EVERY_HOURS * 3600: continue
        text = SCAM_ALERTS[(now // (SCAM_ALERT_EVERY_HOURS * 3600)) % len(SCAM_ALERTS)]
        try:
            await ctx.bot.send_message(cid, text)
            store.set_scam_last(cid, now)
        except Exception:
            pass

async def on_banstats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _can_moderate(update, ctx):
        await update.effective_message.reply_text("Only the owner, elevated users, or admins of a protected group can see this."); return
    s = store.mod_stats()
    await update.effective_message.reply_text(
        f"🛡 *Protection stats*\n"
        f"Protected groups: {s['groups_protected']} (+{s['groups_pending']} pending approval)\n"
        f"Global bans: {s['gbans']}\n"
        f"AI bans: {s['ai_bans']}\n"
        f"Elevated users: {s['elevated']}\n"
        f"Verified members (all groups): {s['verified']}\n"
        f"Waiting on the safety check right now: {s['pending']}",
        parse_mode=ParseMode.MARKDOWN)

# --- Lunetta-style additions (2026-10-25): hashtags, group rules/welcome ---

HASHTAG_RE = re.compile(r"#(\w+)")
TAG_COOLDOWN = {}  # (chat_id, tag) -> ts; one answer per tag per chat per minute

def _first_hashtag(text):
    for t in HASHTAG_RE.findall(text or ""):
        if topics.known(t):
            return t.lower()
    return None

async def _hashtag_answer(update, tag):
    now = int(time.time())
    chat_id = update.effective_chat.id
    key = (chat_id, tag)
    if now - TAG_COOLDOWN.get(key, 0) < 60:
        return None
    if tag == "commands":
        ans = topics.commands_text()
    elif tag == "rules":
        ans = store.get_setting(chat_id, "rules_text") or "No rules set for this group yet — an admin can set them with /setrules <text>."
    elif tag == "welcome":
        ans = store.get_setting(chat_id, "welcome_text") or "No welcome note set for this group yet — an admin can set one with /setwelcome <text>."
    else:
        ans = topics.lookup(tag)
    if ans:
        TAG_COOLDOWN[key] = now
    return ans

async def _set_group_text(update, ctx, key, label, show_cmd):
    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        await update.effective_message.reply_text(f"Set the {label} inside the group."); return
    if not await _can_change(update, ctx):
        await update.effective_message.reply_text(f"Only group admins can set the {label}."); return
    text = " ".join(ctx.args or []).strip()
    if update.message.reply_to_message and update.message.reply_to_message.text:
        text = update.message.reply_to_message.text.strip()
    if not text:
        PENDING_INPUT[(chat.id, update.effective_user.id)] = {"kind": "rules" if key == "rules_text" else "welcome"}
        await update.effective_message.reply_text(f"Easy way: just send the {label} text as your next message and I'll save it. (/cancel stops.)\nOr all at once: /set{label} <text>"); return
    if text.lower() == "clear":
        store.set_setting(chat.id, key, "")
        await update.effective_message.reply_text(f"{label.capitalize()} cleared."); return
    store.set_setting(chat.id, key, text[:2000])
    await update.effective_message.reply_text(f"Saved — anyone can see it with {show_cmd}.")

async def on_setrules(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _set_group_text(update, ctx, "rules_text", "rules", "/rules or #rules")

async def on_rules(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        await update.effective_message.reply_text("Rules live in groups."); return
    text = store.get_setting(chat.id, "rules_text")
    await update.effective_message.reply_text(("📜 Group rules\n\n" + text) if text else "No rules set for this group yet — an admin can set them with /setrules <text>.")

async def on_setwelcome(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _set_group_text(update, ctx, "welcome_text", "welcome", "/welcome")

async def on_welcome(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        await update.effective_message.reply_text("Welcome notes live in groups."); return
    text = store.get_setting(chat.id, "welcome_text")
    await update.effective_message.reply_text(text if text else "No welcome note set for this group yet — an admin can set one with /setwelcome <text>.")

# --- /report + per-group /faq (2026-10-25) ---

REPORT_CD = {}  # (chat_id, user_id) -> ts; one report per user per chat per 5 min

async def on_report(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    msg = update.message
    if chat.type not in ("group", "supergroup"):
        await msg.reply_text("Use /report in a group, as a reply to the message you're reporting."); return
    if not msg.reply_to_message:
        await msg.reply_text("Reply to the message you want to report, with /report."); return
    uid = update.effective_user.id
    now = int(time.time())
    if now - REPORT_CD.get((chat.id, uid), 0) < 300:
        await msg.reply_text("You've already reported something here in the last few minutes — the admins have it."); return
    REPORT_CD[(chat.id, uid)] = now
    target = msg.reply_to_message
    author = target.from_user
    author_name = author.full_name if author else "unknown"
    author_id = author.id if author else 0
    excerpt = (target.text or target.caption or "(no text — media, sticker, or file)")[:200]
    if chat.username:
        link = f"https://t.me/{chat.username}/{target.message_id}"
    elif str(chat.id).startswith("-100"):
        link = f"https://t.me/c/{str(chat.id)[4:]}/{target.message_id}"
    else:
        link = ""
    note = " ".join(ctx.args or [])
    report = (f"🚩 Report in {chat.title or 'a group'}\n"
              f"Reported by: {update.effective_user.full_name} ({uid})\n"
              f"Message by: {author_name} ({author_id})\n"
              f"Text: {excerpt}\n"
              + (f"Note: {note}\n" if note else "")
              + (f"Jump to it: {link}" if link else ""))
    sent, notified = 0, set()
    try:
        admins = await ctx.bot.get_chat_administrators(chat.id)
    except Exception:
        admins = []
    for a in admins:
        u = a.user
        if u.is_bot or u.id == uid: continue
        try:
            await ctx.bot.send_message(u.id, report)
            sent += 1; notified.add(u.id)
        except Exception:
            pass  # an admin who never opened a DM with the bot can't be DM'd
    if OWNER_ID and OWNER_ID != uid and OWNER_ID not in notified:
        try:
            await ctx.bot.send_message(OWNER_ID, report)
            sent += 1
        except Exception:
            pass
    if sent:
        await msg.reply_text(f"🚩 Reported — {sent} admin(s) notified by DM.")
    else:
        await msg.reply_text("🚩 Noted — but no admin could be reached by DM (an admin has to open a chat with me once before I can DM them). Please tag an admin here too.")

async def on_faq(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        await update.effective_message.reply_text("FAQs live in groups."); return
    q = " ".join(ctx.args or []).strip().lower()
    if q:
        a = store.faq_get(chat.id, q)
        await update.effective_message.reply_text(a if a else "No saved answer for that — /faq lists this group's saved questions.")
        return
    qs = store.faq_list(chat.id)
    if not qs:
        await update.effective_message.reply_text("No FAQs saved for this group yet. An admin can add one: /addfaq <question> | <answer>")
    else:
        await update.effective_message.reply_text("❓ This group's FAQs:\n" + "\n".join(f"• {x}" for x in qs) + "\n\nAsk one with /faq <question> — or just type the question in chat.")

async def on_addfaq(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        await update.effective_message.reply_text("Add FAQs inside the group."); return
    if not await _can_change(update, ctx):
        await update.effective_message.reply_text("Only group admins can add FAQs."); return
    parts = (update.message.text or "").split(None, 1)
    raw = parts[1] if len(parts) > 1 else ""
    if not raw:
        PENDING_INPUT[(chat.id, update.effective_user.id)] = {"kind": "faq_q"}
        await update.effective_message.reply_text("Let's add an FAQ the easy way — first, send the *question* as your next message. (/cancel stops.)", parse_mode=ParseMode.MARKDOWN); return
    if "|" not in raw:
        await update.effective_message.reply_text("Usage: /addfaq <question> | <answer>\nExample: /addfaq where do I stake | Use /stake for the steps, or the guide on luncscan.com"); return
    q, a = raw.split("|", 1)
    q, a = q.strip().lower(), a.strip()
    if not q or not a:
        await update.effective_message.reply_text("Both a question and an answer are needed: /addfaq <question> | <answer>"); return
    store.faq_add(chat.id, q[:120], a[:1000], update.effective_user.id)
    await update.effective_message.reply_text(f"✅ FAQ saved: '{q[:120]}' — /faq {q[:120]} shows it, and typing the question in chat works too.")

async def on_delfaq(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        await update.effective_message.reply_text("FAQs live in groups."); return
    if not await _can_change(update, ctx):
        await update.effective_message.reply_text("Only group admins can remove FAQs."); return
    q = " ".join(ctx.args or []).strip().lower()
    if not q:
        await update.effective_message.reply_text("Usage: /delfaq <question>"); return
    if store.faq_remove(chat.id, q):
        await update.effective_message.reply_text("FAQ removed.")
    else:
        await update.effective_message.reply_text("No FAQ with that exact question — /faq lists them.")

# --- Simplify round (2026-10-25): buttons instead of typed commands ---

PENDING_INPUT = {}  # (chat_id, user_id) -> {"kind": faq_q|faq_a|rules|welcome, "q": str}

async def on_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if PENDING_INPUT.pop((update.effective_chat.id, update.effective_user.id), None):
        await update.effective_message.reply_text("Cancelled.")
    else:
        await update.effective_message.reply_text("Nothing to cancel.")

MENU_KB = InlineKeyboardMarkup([
    [InlineKeyboardButton("💰 Price", callback_data="menu:price"), InlineKeyboardButton("📊 Stats", callback_data="menu:stats")],
    [InlineKeyboardButton("🗳 Proposals", callback_data="menu:proposals"), InlineKeyboardButton("🛡 Safety", callback_data="menu:safety")],
    [InlineKeyboardButton("🔗 Links", callback_data="menu:links"), InlineKeyboardButton("🔒 Privacy", callback_data="menu:privacy")],
    [InlineKeyboardButton("📜 Group rules", callback_data="menu:rules"), InlineKeyboardButton("❓ Group FAQ", callback_data="menu:faq")],
    [InlineKeyboardButton("🔄 DEXes", callback_data="menu:dex"), InlineKeyboardButton("🔀 GitHub PRs", callback_data="menu:pr")],
])

async def on_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text("👇 Tap what you need — no commands to remember.\n(📖 Full command list: /help)", reply_markup=MENU_KB)

async def on_menu_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    chat = q.message.chat
    action = q.data.split(":")[1]
    await q.answer()
    md = True
    if action == "price":
        text = await price_text()
    elif action == "stats":
        try: text = await chain.stats_text()
        except Exception: text = "Couldn't fetch chain stats right now."
    elif action == "proposals":
        text = await proposals_text()
    elif action == "safety":
        text = SAFETY_TEXT
    elif action == "links":
        text = LINKS_TEXT
    elif action == "dex":
        text = DEX_TEXT
    elif action == "privacy":
        text = PRIVACY_TEXT
    elif action == "rules":
        md = False
        if chat.type in ("group", "supergroup"):
            t = store.get_setting(chat.id, "rules_text")
            text = ("📜 Group rules\n\n" + t) if t else "No rules set for this group yet — an admin can set them with /setrules."
        else:
            text = "Group rules live in groups — tap 📜 inside a group."
    elif action == "faq":
        md = False
        if chat.type in ("group", "supergroup"):
            qs = store.faq_list(chat.id)
            text = ("❓ This group's FAQs:\n" + "\n".join(f"• {x}" for x in qs) + "\n\nAsk one with /faq <question> — or just type the question in chat.") if qs else "No FAQs saved for this group yet. An admin can add one with /addfaq."
        else:
            text = "Group FAQs live in groups — tap ❓ inside a group."
    elif action == "pr":
        md = False
        rows = store.pr_watch_list(chat.id)
        state = "ON" if store.pr_alerts_enabled(chat.id) else "OFF"
        if rows:
            text = (f"🔀 GitHub PR notifications: {state} for this chat\nWatching:\n"
                    + "\n".join(f"• {r['repo']}" for r in rows)
                    + "\n\nLook one up: /pr <owner/repo> <number>\nAdmins manage this with /pralerts and /prwatch.")
        else:
            text = ("🔀 GitHub PR notifications: no repos watched in this chat yet.\n"
                    "Look one up: /pr <owner/repo> <number>\n"
                    "Admins can follow a repo with /prwatch add <owner/repo>, then /pralerts on.")
    else:
        return
    await ctx.bot.send_message(chat.id, text, parse_mode=ParseMode.MARKDOWN if md else None)

def _panel_text(chat):
    return (f"⚙️ Admin panel — {chat.title or 'this group'}\n"
            f"🛡 Protection: {'ON' if store.mod_is_protected(chat.id) else 'OFF'}\n"
            f"🤖 AI answers: {'ON' if store.ai_enabled(chat.id) else 'OFF'}\n"
            f"⚠️ Scam reminders: {'ON' if store.scam_alerts_enabled(chat.id) else 'OFF'}\n\n"
            "Tap a switch to flip it.")

def _panel_kb(chat):
    rows = [
        [InlineKeyboardButton("🤖 AI answers: ON ✅" if store.ai_enabled(chat.id) else "🤖 AI answers: OFF", callback_data="panel:ai")],
        [InlineKeyboardButton("⚠️ Scam reminders: ON ✅" if store.scam_alerts_enabled(chat.id) else "⚠️ Scam reminders: OFF", callback_data="panel:scam")],
    ]
    if store.mod_is_protected(chat.id):
        rows.append([InlineKeyboardButton("📊 Protection stats", callback_data="panel:stats")])
    else:
        rows.append([InlineKeyboardButton("🛡 Request protection", callback_data="panel:protect")])
    return InlineKeyboardMarkup(rows)

async def on_panel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        await update.effective_message.reply_text("The admin panel works inside a group."); return
    if not (_is_owner(update.effective_user.id) or await _can_change(update, ctx)):
        await update.effective_message.reply_text("Only group admins can use the panel."); return
    await update.effective_message.reply_text(_panel_text(chat), reply_markup=_panel_kb(chat))

async def on_panel_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    chat = q.message.chat
    if not (_is_owner(q.from_user.id) or await _is_group_admin(ctx, chat.id, q.from_user.id)):
        await q.answer("Only group admins can use the panel.", show_alert=True); return
    action = q.data.split(":")[1]
    if action == "ai":
        store.set_ai_enabled(chat.id, not store.ai_enabled(chat.id))
        await q.answer("AI answers " + ("ON" if store.ai_enabled(chat.id) else "OFF"))
    elif action == "scam":
        if not store.mod_is_protected(chat.id):
            await q.answer("Protection isn't on for this group yet — scam reminders come with it.", show_alert=True); return
        store.set_scam_alerts(chat.id, not store.scam_alerts_enabled(chat.id))
        await q.answer("Scam reminders " + ("ON" if store.scam_alerts_enabled(chat.id) else "OFF"))
    elif action == "stats":
        s = store.mod_stats()
        await q.answer()
        await ctx.bot.send_message(chat.id, f"🛡 Protection stats — protected groups: {s['groups_protected']}, global bans: {s['gbans']}, elevated users: {s['elevated']}, verified members: {s['verified']}, waiting on the safety check: {s['pending']}")
        return
    elif action == "protect":
        if store.mod_is_protected(chat.id):
            await q.answer("Already protected 🛡"); return
        row = store.mod_group(chat.id)
        if row is not None:
            await q.answer("Already requested — waiting on the owner's approval.", show_alert=True); return
        store.mod_request_group(chat.id, chat.title or "", q.from_user.id)
        if OWNER_ID:
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Approve", callback_data=f"mod:approve:{chat.id}"),
                InlineKeyboardButton("❌ Deny", callback_data=f"mod:deny:{chat.id}")]])
            try: await ctx.bot.send_message(OWNER_ID, f"🛡 Protection request: {chat.title} (chat id {chat.id}), requested by user {q.from_user.id}.\nTap a button — or use /approve {chat.id} · /deny {chat.id}", reply_markup=kb)
            except Exception: pass
        await q.answer("Request sent to the owner ✅", show_alert=True)
        return
    else:
        return
    try: await q.edit_message_text(_panel_text(chat), reply_markup=_panel_kb(chat))
    except Exception: pass

async def on_mod_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not _is_owner(q.from_user.id):
        await q.answer("Owner only.", show_alert=True); return
    try:
        _, action, cid_s = q.data.split(":")
        chat_id = int(cid_s)
    except Exception:
        await q.answer("Bad button."); return
    if action == "approve":
        if store.mod_approve_group(chat_id):
            await q.answer("Approved ✅")
            try: await q.edit_message_text(f"✅ Approved — protection is ON for chat {chat_id}.")
            except Exception: pass
            try: await ctx.bot.send_message(chat_id, "🛡 Protection is ON for this group: new joiners pass a short safety check before they can post, known scammers are removed automatically, and a first message containing a link gets the sender removed.")
            except Exception: pass
        else:
            await q.answer("That request is already gone.", show_alert=True)
    else:
        store.mod_remove_group(chat_id)
        await q.answer("Denied ❌")
        try: await q.edit_message_text(f"❌ Denied — the protection request from chat {chat_id} was removed.")
        except Exception: pass

async def on_learn(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.effective_message.reply_text("Usage: /learn <word> — try: " + ", ".join(GLOSSARY.keys())); return
    w = " ".join(ctx.args).lower()
    if w in GLOSSARY: await update.effective_message.reply_text(f"📖 *{w}*: {GLOSSARY[w]}", parse_mode=ParseMode.MARKDOWN); return
    if not await ai_guard(update): return
    out = await ai_client.chat([{"role":"system","content":"Explain the crypto/Terra Classic term in 2-3 plain lines for a beginner. No financial advice."},{"role":"user","content":w}], lang=user_lang(update))
    if not out:
        out = ai_client.DAILY_LIMIT_NOTE if budget.exhausted() else "I don't have that one yet — try /learn quorum"
    await update.effective_message.reply_text(out)

# ================= GOV ALERTS (voting + proposals) =================
def gov_keyboard(chat_id):
    s = store.gov_settings(chat_id)
    def lbl(key, name): return f"{chr(9989) if s[key]=='on' else chr(10060)} {name}"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(lbl("gov_alerts", "Proposal alerts (master)"), callback_data="gov:gov_alerts")],
        [InlineKeyboardButton(lbl("gov_new", "New proposal voting"), callback_data="gov:gov_new"),
         InlineKeyboardButton(lbl("gov_ending", "Ending <24h"), callback_data="gov:gov_ending")],
        [InlineKeyboardButton(lbl("gov_result", "Final result"), callback_data="gov:gov_result")],
    ])

def gov_status_text(chat_id):
    s = store.gov_settings(chat_id)
    return (f"🗳️ *Proposal / voting notifications: {'ON' if s['gov_alerts']=='on' else 'OFF'}* for this chat\n"
            f"Tap to turn on/off. Types only fire when the master switch is ON.\n"
            f"• New proposal enters voting: {s['gov_new']}\n• Voting ending in <24h: {s['gov_ending']}\n• Final result (passed/rejected): {s['gov_result']}")

async def on_govalerts(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    if ctx.args and ctx.args[0].lower() in ("on", "off"):
        if not await _can_change(update, ctx):
            await update.effective_message.reply_text("Only group admins can change this group's settings."); return
        store.set_setting(cid, "gov_alerts", ctx.args[0].lower())
    await update.effective_message.reply_text(gov_status_text(cid), reply_markup=gov_keyboard(cid), parse_mode=ParseMode.MARKDOWN)

async def on_gov_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not await _can_change(update, ctx):
        await q.answer("Only group admins can change group settings.", show_alert=True); return
    key = q.data.split(":", 1)[1]; cid = q.message.chat.id
    cur = store.get_setting(cid, key); store.set_setting(cid, key, "off" if cur == "on" else "on")
    await q.answer(f"{key}: {'OFF' if cur=='on' else 'ON'}")
    await q.edit_message_text(gov_status_text(cid), reply_markup=gov_keyboard(cid), parse_mode=ParseMode.MARKDOWN)

async def on_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text("⚙️ *Settings — notifications are your choice*\n🔥 /burnalerts — burn notifications\n🗳️ /govalerts — proposal & voting notifications\n🔀 /pralerts — GitHub PR notifications (repos: /prwatch)\n🏛️ /watchlist — validators watched in this chat", parse_mode=ParseMode.MARKDOWN)

# ================= VALIDATOR WATCH =================
async def on_watchvalidator(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args: await update.effective_message.reply_text("Usage: /watchvalidator <moniker or terravaloper...>"); return
    try:
        v = await chain.find_validator(" ".join(ctx.args))
        if not v: await update.effective_message.reply_text("Validator not found."); return
        store.watch_validator(update.effective_chat.id, v["operator_address"], v["description"]["moniker"], json.dumps(chain.snapshot(v)))
        await update.effective_message.reply_text(f"👀 Watching *{v['description']['moniker']}* in this chat.\nI'll alert here if it gets jailed, changes status or commission, or its voting power moves >5%.", parse_mode=ParseMode.MARKDOWN)
    except Exception: await update.effective_message.reply_text("Couldn't add that validator right now.")

async def on_unwatchvalidator(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args: await update.effective_message.reply_text("Usage: /unwatchvalidator <terravaloper...> (see /watchlist)"); return
    n = store.unwatch_validator(update.effective_chat.id, ctx.args[0])
    await update.effective_message.reply_text("Stopped watching that validator in this chat." if n else "That validator isn't on this chat's watchlist.")

async def on_watchlist(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    rows = store.list_watched(update.effective_chat.id)
    if not rows: await update.effective_message.reply_text("No validators watched in this chat yet. Add one: /watchvalidator <name>"); return
    lines = ["👀 *Watched in this chat:*"] + [f"• {r['moniker']} — {r['valoper']}" for r in rows]
    await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)

# ================= GITHUB PR INFO + ALERTS =================
def _msg_thread(update):
    """Forum topic the command was run in, if any — notifications for a
    subscription created there post back into that same topic."""
    return getattr(update.message, "message_thread_id", None)

async def _can_change_pr(update, ctx):
    """PR settings: the bot owner, or a group admin (in DM: the user)."""
    return _is_owner(update.effective_user.id) or await _can_change(update, ctx)

def pr_alerts_text(chat_id):
    on = store.pr_alerts_enabled(chat_id)
    rows = store.pr_watch_list(chat_id)
    lines = [f"🔀 *GitHub PR notifications: {'ON' if on else 'OFF'}* for this chat"]
    if rows:
        lines.append("Watching:")
        lines += [f"• {r['repo']}" for r in rows]
    else:
        lines.append("No repos watched yet — /prwatch add <owner/repo>")
    lines.append("Usage: /pralerts on · /pralerts off · /prwatch add <owner/repo> · /pr <owner/repo> <number>")
    return "\n".join(lines)

async def on_pralerts(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    arg = (ctx.args or [""])[0].lower()
    if arg in ("on", "off"):
        if not await _can_change_pr(update, ctx):
            await update.effective_message.reply_text("Only group admins can change this group's settings."); return
        on = arg == "on"
        store.set_pr_alerts(chat.id, on)
        if on and not store.pr_watch_list(chat.id):
            for repo in github_pr.DEFAULT_REPOS:
                store.pr_watch_add(chat.id, repo, _msg_thread(update))
            await update.effective_message.reply_text(
                "🔀 PR notifications ON — no repos were configured for this chat, so it now watches the defaults:\n"
                + "\n".join("• " + r for r in github_pr.DEFAULT_REPOS)
                + "\nChange them with /prwatch add <owner/repo> · /prwatch remove <owner/repo>")
            return
    await update.effective_message.reply_text(pr_alerts_text(chat.id), parse_mode=ParseMode.MARKDOWN)

async def on_prwatch(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    args = ctx.args or []
    sub = args[0].lower() if args else ""
    if sub in ("add", "remove"):
        if not await _can_change_pr(update, ctx):
            await update.effective_message.reply_text("Only group admins can change this group's settings."); return
        if len(args) < 2 or not github_pr.valid_repo(args[1]):
            await update.effective_message.reply_text("Usage: /prwatch add <owner/repo> — e.g. /prwatch add terra-classic-io/website"); return
        repo = args[1]
        if sub == "add":
            store.pr_watch_add(chat.id, repo, _msg_thread(update))
            note = "" if store.pr_alerts_enabled(chat.id) else "\nNotifications are OFF for this chat — turn them on with /pralerts on."
            await update.effective_message.reply_text(f"👀 Watching {repo} in this chat.{note}")
        else:
            n = store.pr_watch_remove(chat.id, repo)
            await update.effective_message.reply_text(f"Stopped watching {repo} in this chat." if n else f"{repo} isn't on this chat's watch list.")
        return
    rows = store.pr_watch_list(chat.id)
    if not rows:
        await update.effective_message.reply_text("No repos watched in this chat yet. Add one: /prwatch add <owner/repo>\nNotifications are managed with /pralerts on · /pralerts off."); return
    state = "ON" if store.pr_alerts_enabled(chat.id) else "OFF"
    lines = [f"👀 *PR watch — notifications {state}*"] + [f"• {r['repo']}" for r in rows]
    lines.append("Add: /prwatch add <owner/repo> · Remove: /prwatch remove <owner/repo>")
    await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)

async def on_pr(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    watched = [r["repo"] for r in store.pr_watch_list(update.effective_chat.id)]
    repo, number, err = github_pr.parse_pr_args(ctx.args, watched)
    if err:
        await update.effective_message.reply_text(err); return
    try:
        pr, latest = await github_pr.fetch_pr_detail(repo, number)
    except github_pr.GhError as e:
        if e.status == 404:
            await update.effective_message.reply_text(f"Couldn't find PR #{number} in {repo} — check the repo and number.")
        elif github_pr.is_rate_limited(e):
            await update.effective_message.reply_text("GitHub is rate-limiting right now — try again in a bit.")
        else:
            await update.effective_message.reply_text("Couldn't fetch that PR from GitHub right now.")
        return
    except Exception:
        await update.effective_message.reply_text("Couldn't fetch that PR from GitHub right now.")
        return
    await update.effective_message.reply_text(github_pr.format_pr_detail(repo, pr, latest))

# ================= WATCH JOBS =================
async def job_gov_check(ctx: ContextTypes.DEFAULT_TYPE):
    try: props = await chain.proposals_voting()
    except Exception: return
    seen_raw = store.get_setting(0, "gov_seen_voting") or ""
    seen = set(x for x in seen_raw.split(",") if x)
    tracked_raw = store.get_setting(0, "gov_tracked") or "{}"
    try: tracked = json.loads(tracked_raw)
    except Exception: tracked = {}
    chats = store.chats_with_gov_on(); now = datetime.datetime.now(datetime.timezone.utc)
    for pr in props:
        pid = str(pr["id"]); tracked[pid] = pr.get("status", "PROPOSAL_STATUS_VOTING_PERIOD")
        if pid not in seen:
            seen.add(pid)
            for cid in chats:
                if store.get_setting(cid, "gov_new") == "on":
                    try: await ctx.bot.send_message(cid, f"🗳️ New proposal in voting: *{pid} — {pr.get('title','')}*\nVoting ends: {pr.get('voting_end_time','')} UTC\nDetail: /proposal {pid}", parse_mode=ParseMode.MARKDOWN)
                    except Exception: pass
        # ending soon (<24h), once per proposal
        end_key = f"gov_ending_sent_{pid}"
        try:
            end = datetime.datetime.fromisoformat(pr["voting_end_time"].replace("Z", "+00:00"))
            if datetime.timedelta(0) < (end - now) < datetime.timedelta(hours=24) and not store.get_setting(0, end_key):
                store.set_setting(0, end_key, "1")
                for cid in chats:
                    if store.get_setting(cid, "gov_ending") == "on":
                        try: await ctx.bot.send_message(cid, f"⏰ Voting ends in <24h: *{pid} — {pr.get('title','')}*\nEnds: {pr['voting_end_time']} UTC\nUse /proposal {pid} for the live tally", parse_mode=ParseMode.MARKDOWN)
                        except Exception: pass
        except Exception: pass
    # results: tracked proposals no longer in voting list -> fetch final status once
    voting_ids = {str(pr["id"]) for pr in props}
    for pid in list(tracked.keys()):
        if pid not in voting_ids:
            try:
                final = await chain.proposal_detail(pid); status = final.get("status", "")
            except Exception: continue
            del tracked[pid]
            for cid in chats:
                if store.get_setting(cid, "gov_result") == "on":
                    try: await ctx.bot.send_message(cid, f"🗳️ Proposal *{pid}* finished: *{status}*\n{final.get('title','')}", parse_mode=ParseMode.MARKDOWN)
                    except Exception: pass
    store.set_setting(0, "gov_seen_voting", ",".join(sorted(seen)))
    store.set_setting(0, "gov_tracked", json.dumps(tracked))

async def job_validator_check(ctx: ContextTypes.DEFAULT_TYPE):
    by_val = {}
    for r in store.list_watched(): by_val.setdefault(r["valoper"], []).append(r)
    for valoper, rows in by_val.items():
        try: v = await chain.validator_by_addr(valoper)
        except Exception: continue
        new = chain.snapshot(v)
        for r in rows:
            try: old = json.loads(r["snapshot"])
            except Exception: old = {}
            alerts = []
            if old.get("jailed") != new["jailed"]: alerts.append(f"jailed changed: {old.get('jailed')} → {new['jailed']}")
            if old.get("status") != new["status"]: alerts.append(f"status changed: {old.get('status')} → {new['status']}")
            if old.get("commission") != new["commission"]: alerts.append(f"commission changed: {float(old.get('commission',0))*100:.2f}% → {float(new['commission'])*100:.2f}%")
            if old.get("tokens") and abs(new["tokens"] - old["tokens"]) / old["tokens"] > 0.05:
                alerts.append(f"voting power moved {(new['tokens']-old['tokens'])/old['tokens']*100:+.1f}% → {new['tokens']/1e6:,.0f} LUNC")
            if alerts:
                try: await ctx.bot.send_message(r["chat_id"], f"🏛️ Validator watch — *{r['moniker']}*\n" + "\n".join("• " + a for a in alerts), parse_mode=ParseMode.MARKDOWN)
                except Exception: pass
            store.update_snapshot(r["chat_id"], valoper, json.dumps(new))

# --- Background GitHub PR checks (job queue, ~5 min) ---
PR_SEND_GAP = 1.0   # max ~1 notification per second per chat
_PR_LAST_SEND = {}  # chat_id -> last notification ts (in-memory pacing)

async def job_pr_check(ctx: ContextTypes.DEFAULT_TYPE):
    subs = store.pr_active_subscriptions()
    if not subs: return
    by_repo = {}
    for s in subs: by_repo.setdefault(s["repo"], []).append(s)
    skip = (GITHUB_BOT_LOGIN,) if GITHUB_BOT_LOGIN else ()
    for repo, rows in by_repo.items():
        try:
            events, new_state = await github_pr.poll_repo(repo, store.pr_get_state(repo), skip_logins=skip)
        except github_pr.GhError as e:
            # 403/429 = GitHub rate limit: back off quietly, retry next cycle.
            print(f"pr poll {repo}: GitHub HTTP {e.status} — backing off this cycle")
            return
        except Exception as e:
            print(f"pr poll {repo}: {e}")
            continue
        store.pr_set_state(repo, new_state)
        for ev in events:
            text = github_pr.format_event(ev)
            for s in rows:
                cid = s["chat_id"]
                wait = PR_SEND_GAP - (time.time() - _PR_LAST_SEND.get(cid, 0))
                if wait > 0: await asyncio.sleep(wait)
                kw = {"message_thread_id": s["thread_id"]} if s.get("thread_id") else {}
                try:
                    await ctx.bot.send_message(cid, text, **kw)
                    _PR_LAST_SEND[cid] = time.time()
                except Exception: pass

# --- Background burn checks (job queue) ---
async def job_burn_check(ctx: ContextTypes.DEFAULT_TYPE):
    rate = await burn_mod.get_burn_tax_rate()
    supply = await burn_mod.get_lunc_supply()
    last_rate = store.get_setting(0, "last_burn_rate")
    last_supply = store.get_setting(0, "last_supply")
    chats = store.chats_with_burn_on()
    if rate is not None:
        if last_rate is not None and float(last_rate) != rate:
            for cid in chats:
                if store.get_setting(cid, "burn_rate") == "on":
                    try: await ctx.bot.send_message(cid, f"🔥 Burn tax rate CHANGED: {float(last_rate)*100:.2f}% → {rate*100:.2f}%\nEffective burn is 80% of the tax. Source: PublicNode LCD.")
                    except Exception: pass
        store.set_setting(0, "last_burn_rate", rate)
    if supply is not None:
        if last_supply is not None:
            drop = float(last_supply) - supply
            if drop >= BIG_BURN_THRESHOLD:
                for cid in chats:
                    if store.get_setting(cid, "burn_big") == "on":
                        try: await ctx.bot.send_message(cid, f"🔥 Big burn detected: LUNC supply dropped {drop:,.0f} LUNC between checks (net of minting).\nNew total supply: {supply:,.0f} LUNC. Source: PublicNode LCD.")
                        except Exception: pass
        store.set_setting(0, "last_supply", supply)

async def job_burn_daily(ctx: ContextTypes.DEFAULT_TYPE):
    rate = await burn_mod.get_burn_tax_rate()
    supply = await burn_mod.get_lunc_supply()
    last_daily = store.get_setting(0, "last_daily_supply")
    msg = burn_mod.burn_explainer(rate)
    if supply is not None and last_daily is not None:
        drop = float(last_daily) - supply
        msg += f"\n\nSupply change since last daily report: {-drop:+,.0f} LUNC (negative = net burned)."
    if supply is not None: store.set_setting(0, "last_daily_supply", supply)
    for cid in store.chats_with_burn_on():
        if store.get_setting(cid, "burn_daily") == "on":
            try: await ctx.bot.send_message(cid, f"🔥 Daily Burn Report\n\n{msg}", parse_mode=ParseMode.MARKDOWN)
            except Exception: pass

async def on_proposal(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.effective_message.reply_text("Usage: /proposal 12234"); return
    pid = ctx.args[0]
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(f"{LCD}/cosmos/gov/v1/proposals/{pid}"); r.raise_for_status()
            p = r.json()["proposal"]
        extra = ""
        try:
            tally = await chain.proposal_tally(pid); extra = "\n\n" + chain.tally_text(tally)
        except Exception: pass
        await send_long(update, f"🗳️ Proposal {pid}: {p.get('title','')}\nStatus: {p.get('status')}\nVoting ends: {p.get('voting_end_time')} UTC{extra}")
    except Exception as e:
        await update.effective_message.reply_text(f"Couldn't fetch proposal {pid} right now.")

async def on_price(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get("https://api.coingecko.com/api/v3/simple/price?ids=terra-luna&vs_currencies=usd&include_24hr_change=true"); r.raise_for_status()
            d = r.json()["terra-luna"]
        await update.effective_message.reply_text(f"LUNC (Terra Classic): ${d['usd']} ({d.get('usd_24h_change',0):.2f}% 24h) — via CoinGecko, check live before trading.")
    except Exception:
        await update.effective_message.reply_text("Couldn't fetch price right now.")

async def on_edited_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Protected groups: an edit gets the anti-scam checks too —
    blacklisted words, and links swapped in after a clean first post
    (compared against the originally logged text; for a member still
    on a fresh-account hold, ANY link in an edit counts as a swap)."""
    msg = update.edited_message
    if not msg or not msg.text or not msg.from_user: return
    chat, user, text = msg.chat, msg.from_user, msg.text
    if chat.type not in ("group", "supergroup") or user.is_bot: return
    if not store.mod_is_protected(chat.id):
        # Unprotected group: only the per-group phrase filter applies.
        await _mute_filter_check(ctx, chat, user, text, msg)
        return
    if _is_owner(user.id) or store.is_elevated(user.id): return
    low = text.lower()
    bad = next((w for w in store.blacklist_all() if w in low), None)
    swap = False
    if not bad:
        old = store.message_text(chat.id, msg.message_id)
        if old is not None:
            swap = seclogic.edit_adds_link(old, text)
        else:
            fh = store.fresh_get(chat.id, user.id)
            if fh and fh["until_ts"] > int(time.time()):
                swap = seclogic.has_link(text)
    if not bad and not swap:
        # Protected, but no blacklist/link hit — the phrase filter
        # still applies (checked after the blacklist, so no overlap).
        await _mute_filter_check(ctx, chat, user, text, msg)
        return
    if await _is_group_admin(ctx, chat.id, user.id): return
    try: await msg.delete()
    except Exception: pass
    try:
        await ctx.bot.ban_chat_member(chat.id, user.id)
        await ctx.bot.unban_chat_member(chat.id, user.id, only_if_banned=True)
    except Exception: pass
    why = f"edited a message to add a blacklisted word ('{bad}')" if bad else "edited a message to sneak in a link"
    try: await ctx.bot.send_message(chat.id, f"🚫 A member was removed: they {why} (anti-scam protection). They may rejoin and try again.")
    except Exception: pass

async def on_media_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Protected groups: media captions get the text checks —
    blacklisted words and the first-message link rule read captions,
    so a scam link can't ride in under a photo."""
    msg = update.message
    if not msg or not msg.caption: return
    chat, user, text = update.effective_chat, update.effective_user, msg.caption
    if chat.type not in ("group", "supergroup") or user.is_bot: return
    if not store.mod_is_protected(chat.id):
        # Unprotected group: only the per-group phrase filter applies.
        await _mute_filter_check(ctx, chat, user, text, msg)
        return
    first = store.first_msg_mark(chat.id, user.id)
    if _is_owner(user.id) or store.is_elevated(user.id): return
    low = text.lower()
    bad = next((w for w in store.blacklist_all() if w in low), None)
    has_link = any(e.type in ("url", "text_link") for e in (msg.caption_entities or [])) or bool(LINK_RE.search(text))
    if not (bad or (first and has_link and not seclogic.all_links_allowlisted(text))):
        # Protected, but no blacklist/link hit — the phrase filter
        # still applies (checked after the blacklist, so no overlap).
        await _mute_filter_check(ctx, chat, user, text, msg)
        return
    if await _is_group_admin(ctx, chat.id, user.id): return
    try: await msg.delete()
    except Exception: pass
    try:
        await ctx.bot.ban_chat_member(chat.id, user.id)
        await ctx.bot.unban_chat_member(chat.id, user.id, only_if_banned=True)
    except Exception: pass
    why = f"a photo/video caption contained a blacklisted word ('{bad}')" if bad else "their first post here was a photo/video whose caption contained a link"
    try: await ctx.bot.send_message(chat.id, f"🚫 A member was removed: {why} (anti-scam protection). They may rejoin and try again.")
    except Exception: pass

async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    chat, user, text = update.effective_chat, update.effective_user, update.message.text
    name = user.full_name + (f" (@{user.username})" if user.username else "")
    # Group protection (protected groups only): a blacklisted word in any
    # message, or a link in a member's FIRST tracked message, removes the
    # sender (Cosmobot's anti-scam rules). Owner, elevated users, and the
    # group's own admins are exempt. Runs before logging, so a deleted
    # scam message never reaches summaries.
    if chat.type in ("group", "supergroup") and not user.is_bot and store.mod_is_protected(chat.id):
        first = store.first_msg_mark(chat.id, user.id)
        if not _is_owner(user.id) and not store.is_elevated(user.id):
            _admin = None
            async def _exempt_admin():
                nonlocal _admin
                if _admin is None:
                    _admin = await _is_group_admin(ctx, chat.id, user.id)
                return _admin
            now = int(time.time())
            # Flood control: a burst of messages inside a few seconds is
            # a spam run, not conversation. Delete + timed mute; a repeat
            # within the hour earns the longer mute.
            fkey = (chat.id, user.id)
            ft = [t for t in FLOOD_TIMES.get(fkey, []) if now - t < FLOOD_WINDOW]
            ft.append(now); FLOOD_TIMES[fkey] = ft
            if len(ft) > FLOOD_MAX and not await _exempt_admin():
                FLOOD_TIMES[fkey] = []
                off = FLOOD_OFFENSES.get(fkey)
                count = (off[0] + 1) if off and now - off[1] < 3600 else 1
                FLOOD_OFFENSES[fkey] = [count, now]
                minutes = FLOOD_MUTE2_MINUTES if count > 1 else FLOOD_MUTE_MINUTES
                try: await update.message.delete()
                except Exception: pass
                until = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=minutes)
                try: await ctx.bot.restrict_chat_member(chat.id, user.id, permissions=NO_PERMS, until_date=until)
                except Exception: pass
                store.mod_log_add(0, "flood mute", user.id, chat.id, f"{minutes} min, offense {count}")
                try: await ctx.bot.send_message(chat.id, f"🔇 A member was muted for {minutes} minutes for flooding (anti-spam protection).")
                except Exception: pass
                return
            # Cross-group repeat: the same long message landing in a
            # second protected group within minutes is the classic
            # scam-broadcast pattern. Delete + mute here, flag the owner.
            fp = seclogic.fingerprint(text)
            if fp and not await _exempt_admin():
                for k in [k for k, v in REPEAT_SEEN.items() if now - v["ts"] > REPEAT_WINDOW]:
                    REPEAT_SEEN.pop(k, None)
                seen = REPEAT_SEEN.setdefault(fp, {"chats": {}, "ts": now})
                others = [c for c in seen["chats"] if c != chat.id]
                seen["chats"][chat.id] = now
                if others:
                    try: await update.message.delete()
                    except Exception: pass
                    until = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=REPEAT_MUTE_MINUTES)
                    try: await ctx.bot.restrict_chat_member(chat.id, user.id, permissions=NO_PERMS, until_date=until)
                    except Exception: pass
                    store.mod_log_add(0, "repeat flag", user.id, chat.id, "same long message in 2+ protected groups")
                    if OWNER_ID:
                        try: await ctx.bot.send_message(OWNER_ID, f"🚩 Cross-group repeat flagged\nUser: {user.id} ({name})\nPosted the same long message in chat {others[0]} and now in chat {chat.id} — deleted + muted {REPEAT_MUTE_MINUTES} min here.\nText: {text[:200]}")
                        except Exception: pass
                    try: await ctx.bot.send_message(chat.id, f"🚫 A member was muted: the same long message was just posted across protected groups (a common scam pattern).")
                    except Exception: pass
                    return
            low = text.lower()
            bad = next((w for w in store.blacklist_all() if w in low), None)
            has_link = any(e.type in ("url", "text_link") for e in (update.message.entities or [])) or bool(LINK_RE.search(text))
            # First-message links to allowlisted official domains are fine.
            if bad or (first and has_link and not seclogic.all_links_allowlisted(text)):
                if not await _exempt_admin():
                    try: await update.message.delete()
                    except Exception: pass
                    try:
                        await ctx.bot.ban_chat_member(chat.id, user.id)
                        await ctx.bot.unban_chat_member(chat.id, user.id, only_if_banned=True)
                    except Exception: pass
                    why = f"contained a blacklisted word ('{bad}')" if bad else "their first message here contained a link"
                    try: await ctx.bot.send_message(chat.id, f"🚫 A member was removed: their message {why} (anti-scam protection). They may rejoin and try again.")
                    except Exception: pass
                    return
    # Per-group phrase filter: independent of /protect — active in any
    # group that has phrases configured. Sits after the protection
    # block, so in a protected group the global blacklist (delete +
    # remove) has already fired and this never double-punishes; a
    # filter-only hit still lands here. Runs before logging, like the
    # blacklist, so a removed message never reaches summaries.
    if chat.type in ("group", "supergroup") and user and not user.is_bot:
        if await _mute_filter_check(ctx, chat, user, text, update.message):
            return
    # Log group messages for summaries
    if chat.type in ("group", "supergroup"):
        store.log_message(chat.id, user.id, name, text, update.message.message_id)
    # Step-by-step input (easy /addfaq, /setrules, /setwelcome flows):
    # if this user is mid-flow in this chat, this message is their answer.
    if chat.type in ("group", "supergroup"):
        _pend = PENDING_INPUT.get((chat.id, user.id))
        if _pend:
            _kind = _pend["kind"]
            if _kind == "faq_q":
                PENDING_INPUT[(chat.id, user.id)] = {"kind": "faq_a", "q": text.strip().lower()[:120]}
                await update.effective_message.reply_text("Got it. Now send the *answer* for that question.", parse_mode=ParseMode.MARKDOWN)
                return
            PENDING_INPUT.pop((chat.id, user.id), None)
            if _kind == "faq_a":
                store.faq_add(chat.id, _pend["q"], text.strip()[:1000], user.id)
                await update.effective_message.reply_text(f"✅ FAQ saved: '{_pend['q']}' — typing that question in chat now answers it.")
            elif _kind == "rules":
                store.set_setting(chat.id, "rules_text", text.strip()[:2000])
                await update.effective_message.reply_text("📜 Rules saved — /rules or #rules shows them.")
            elif _kind == "welcome":
                store.set_setting(chat.id, "welcome_text", text.strip()[:2000])
                await update.effective_message.reply_text("👋 Welcome note saved — new joiners will see it.")
            return
    # Hashtag topics (groups): #memo, #scammed, ... get a ready answer
    if chat.type in ("group", "supergroup"):
        _tag = _first_hashtag(text)
        if _tag:
            _ans = await _hashtag_answer(update, _tag)
            if _ans:
                await update.effective_message.reply_text(_ans)
                return
        # FAQ exact match: a message that IS a saved question gets its answer
        if 0 < len(text) <= 120:
            _fa = store.faq_get(chat.id, text.strip().lower())
            if _fa and int(time.time()) - TAG_COOLDOWN.get((chat.id, "faq"), 0) >= 60:
                TAG_COOLDOWN[(chat.id, "faq")] = int(time.time())
                await update.effective_message.reply_text(_fa)
                return
    # Mention = ask
    bot_name = (await ctx.bot.get_me()).username
    if bot_name and f"@{bot_name}" in text:
        q = text.replace(f"@{bot_name}", "").strip()
        if q:
            if not await ai_guard(update): return
            ctx.args = q.split()
            # reuse ask logic with cleaned question: temporarily set message text path
            out = await ai_client.chat([
                {"role":"system","content":"You are LUNC Assistant Bot, a standalone general AI assistant. Answer clearly and concisely. Trusted references you may cite: Finder (finder.terra.money/classic) for on-chain verification, LuncScan (luncscan.com) for explorer data and beginner staking/validator guides, LUNCDash (luncdash.com) for dashboards, and StatsBin (statsbin.com) for chain stats and upgrade countdowns. Terra Classic validators discuss governance and day-to-day operations in the Transparent Validator Chat on Telegram (t.me/transparentvalidatorchat)."},
                {"role":"user","content": q}], lang=user_lang(update))
            if not out:
                out = ai_client.DAILY_LIMIT_NOTE if budget.exhausted() else "AI isn't configured yet (no AI_API_KEY)."
            await send_long(update, out)
        return
    # DM: any long text = summarize it
    if chat.type == "private" and len(text) > 600 and not text.startswith("/"):
        if not AI_ENABLED:
            rows = [{"user_name": name, "text": text, "ts": int(time.time())}]
            await send_long(update, fallback_text(rows))
            return
        if not await ai_guard(update): return
        rows = [{"user_name": name, "text": text, "ts": int(time.time())}]
        out = await ai_client.summarize(rows, lang=user_lang(update))
        await send_long(update, out)

# --- Owner issue alerts (2026-10-25): anything that goes wrong in a
# handler or background job DMs the owner, throttled (same problem at
# most once an hour, max 6 alerts an hour) so a repeating failure
# can't spam him. Honest limit: if the whole process dies (Railway
# outage), the bot can't report its own death — that's an outside
# watchdog's job, like the Garuda bot has.
ALERTS = alerts_mod.AlertThrottler()

async def _alert_owner(bot, where, err):
    if not OWNER_ID: return
    key = f"{where}:{type(err).__name__}"
    if not ALERTS.allow(key, int(time.time())): return
    when = datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M UTC")
    try:
        await bot.send_message(OWNER_ID, f"⚠️ Bot issue — {where}\n{type(err).__name__}: {str(err)[:300]}\nTime: {when}\nThe bot is still running — this is an alert, not a crash report. The same problem won't re-alert for an hour.")
    except Exception: pass

async def on_error(update, ctx: ContextTypes.DEFAULT_TYPE):
    err = ctx.error
    if err is None: return
    where = "a background job or handler"
    try:
        if update is not None and getattr(update, "callback_query", None):
            where = f"button tap '{(update.callback_query.data or '')[:40]}'"
        elif update is not None and update.effective_message and update.effective_message.text:
            where = f"message '{update.effective_message.text[:40]}'"
        elif ctx.job is not None:
            where = f"background job '{ctx.job.name or 'unnamed'}'"
    except Exception: pass
    print(f"ERROR in {where}: {type(err).__name__}: {err}")
    try: await _alert_owner(ctx.bot, where, err)
    except Exception: pass

async def _apply_profile_photo():
    """Re-apply the bot's profile photo (owner's mascot logo) on boot so
    redeploys never lose it. PTB 21.6 predates the setMyProfilePhoto input
    classes, so post the multipart form to the Bot API directly with httpx.
    Never raises — a photo failure must not block startup."""
    try:
        _pf = pathlib.Path(__file__).with_name("bot-profile-512.png")
        if not _pf.exists():
            return
        _url = f"https://api.telegram.org/bot{TOKEN}/setMyProfilePhoto"
        _data = {"photo": json.dumps({"type": "static", "photo": "attach://photo"})}
        _files = {"photo": ("bot-profile-512.png", _pf.read_bytes(), "image/png")}
        async with httpx.AsyncClient(timeout=30) as _cli:
            _resp = await _cli.post(_url, data=_data, files=_files)
        _body = _resp.json()
        if _body.get("ok"):
            print("profile photo: applied")
        else:
            print(f"profile photo: {_body.get('description', 'unknown error')}")
    except Exception as e:
        print(f"profile photo: {e}")

async def post_init(app: Application):
    try:
        await app.bot.set_my_description("LUNC Assistant Bot — I summarize busy group chats into a quick TL;DR and answer questions. Use /summary, /catchup, /ask in a group, or DM me a long text to summarize.")
        await app.bot.set_my_short_description("Summarizes hundreds of group messages into a quick summary + AI assistant.")
        await app.bot.set_my_commands([
            ("summary","Summarize group messages"),("catchup","What you missed"),("tldr","Shrink a message (reply to it)"),
            ("ask","Ask me anything"),("proposals","Proposals voting now"),("proposal","Proposal + tally"),("price","LUNC + USTC price"),("stats","Chain stats"),("burn","Live burn tax info"),("burnalerts","Burn notifications on/off"),("govalerts","Proposal alerts on/off"),("pr","GitHub PR info"),("pralerts","GitHub PR alerts on/off"),("prwatch","Repos watched for PR alerts"),("wallet","Public wallet lookup"),("token","CW20 token info"),("validators","Top validators"),("watchvalidator","Watch a validator"),("rank","Your rank in this chat"),("language","Choose your language"),("privacy","Privacy & security info"),("dex","DEXes on Luna Classic"),("freegames","Play Luna Classic games"),("protect","Request scam protection (group admins)"),("aiban","AI-ban a user (moderators)"),("appeal","Appeal a ban (in DM)"),("rules","This group's rules"),("menu","Buttons menu — no typing"),("panel","Admin panel (group admins)"),("help","All commands")])
        # Profile photo (owner's logo) — re-applied on boot so redeploys never lose it
        await _apply_profile_photo()
        print("LUNC Assistant Bot: description + commands set")
        if AI_ENABLED and not getattr(ai_client, "AI_API_KEY", ""):
            await _alert_owner(app.bot, "startup check", RuntimeError("AI is ON but AI_API_KEY is not set in Railway — AI features will answer 'not configured' until the key is added."))
    except Exception as e:
        print(f"post_init: {e}")

def main():
    if not TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN is missing — paste it in Railway env vars (never in chat/repo).")
    _builder = Application.builder().token(TOKEN).post_init(post_init)
    _proxy = os.getenv("OUTBOUND_PROXY")
    if _proxy: _builder = _builder.proxy(_proxy).get_updates_proxy(_proxy)
    app = _builder.build()
    app.add_error_handler(on_error)
    if TypeHandler is not None:
        # Usage observer first (group -1): passive metadata counting
        # for the owner's daily usage report. Never blocks handlers.
        app.add_handler(TypeHandler(Update, on_observe_update), group=-1)
    app.add_handler(CommandHandler("start", on_start))
    app.add_handler(CommandHandler("botstats", on_botstats))
    app.add_handler(CommandHandler("help", on_help))
    app.add_handler(CommandHandler("rank", on_rank))
    app.add_handler(CommandHandler("rankset", on_rankset))
    app.add_handler(CommandHandler("rankclear", on_rankclear))
    app.add_handler(CommandHandler("language", on_language))
    app.add_handler(CommandHandler("summary", on_summary))
    app.add_handler(CommandHandler("catchup", on_catchup))
    app.add_handler(CommandHandler("tldr", on_tldr))
    app.add_handler(CommandHandler("ask", on_ask))
    app.add_handler(CommandHandler("proposal", on_proposal))
    app.add_handler(CommandHandler("price", on_price2))
    app.add_handler(CommandHandler("burn", on_burn))
    app.add_handler(CommandHandler("stats", on_stats))
    app.add_handler(CommandHandler("convert", on_convert))
    app.add_handler(CommandHandler("proposals", on_proposals))
    app.add_handler(CommandHandler("wallet", on_wallet))
    app.add_handler(CommandHandler("token", on_token))
    app.add_handler(CommandHandler("validators", on_validators))
    app.add_handler(CommandHandler("validator", on_validator_info))
    app.add_handler(CommandHandler("stake", on_stake))
    app.add_handler(CommandHandler("calc", on_calc))
    app.add_handler(CommandHandler("links", on_links))
    app.add_handler(CommandHandler("dex", on_dex))
    app.add_handler(CommandHandler("freegames", on_games))
    app.add_handler(CommandHandler("games", on_games))
    app.add_handler(CommandHandler("safety", on_safety))
    app.add_handler(CommandHandler("learn", on_learn))
    app.add_handler(CommandHandler("govalerts", on_govalerts))
    app.add_handler(CommandHandler("pr", on_pr))
    app.add_handler(CommandHandler("pralerts", on_pralerts))
    app.add_handler(CommandHandler("prwatch", on_prwatch))
    app.add_handler(CommandHandler("watchvalidator", on_watchvalidator))
    app.add_handler(CommandHandler("unwatchvalidator", on_unwatchvalidator))
    app.add_handler(CommandHandler("watchlist", on_watchlist))
    app.add_handler(CommandHandler("burnalerts", on_burnalerts))
    app.add_handler(CommandHandler("settings", on_settings))
    app.add_handler(CommandHandler("privacy", on_privacy))
    app.add_handler(CommandHandler("aion", on_aion))
    app.add_handler(CommandHandler("aioff", on_aioff))
    app.add_handler(CommandHandler("protect", on_protect))
    app.add_handler(CommandHandler("unprotect", on_unprotect))
    app.add_handler(CommandHandler("approve", on_approve))
    app.add_handler(CommandHandler("deny", on_deny))
    app.add_handler(CommandHandler("groups", on_groups))
    app.add_handler(CommandHandler("gban", on_gban))
    app.add_handler(CommandHandler("gunban", on_gunban))
    app.add_handler(CommandHandler("gbans", on_gbans))
    app.add_handler(CommandHandler("aiban", on_aiban))
    app.add_handler(CommandHandler("aiunban", on_aiunban))
    app.add_handler(CommandHandler("aibans", on_aibans))
    app.add_handler(CommandHandler("modlog", on_modlog))
    app.add_handler(CommandHandler("appeal", on_appeal))
    app.add_handler(CommandHandler("elevate", on_elevate))
    app.add_handler(CommandHandler("unelevate", on_unelevate))
    app.add_handler(CommandHandler("elevated", on_elevated))
    app.add_handler(CommandHandler("mute", on_mute))
    app.add_handler(CommandHandler("unmute", on_unmute))
    app.add_handler(CommandHandler("blacklist", on_blacklist))
    app.add_handler(CommandHandler("muteword", on_muteword))
    app.add_handler(CommandHandler("raid", on_raid))
    app.add_handler(CommandHandler("scamalerts", on_scamalerts))
    app.add_handler(CommandHandler("banstats", on_banstats))
    app.add_handler(CommandHandler("setrules", on_setrules))
    app.add_handler(CommandHandler("rules", on_rules))
    app.add_handler(CommandHandler("setwelcome", on_setwelcome))
    app.add_handler(CommandHandler("welcome", on_welcome))
    app.add_handler(CommandHandler("report", on_report))
    app.add_handler(CommandHandler("faq", on_faq))
    app.add_handler(CommandHandler("addfaq", on_addfaq))
    app.add_handler(CommandHandler("delfaq", on_delfaq))
    app.add_handler(CommandHandler("menu", on_menu))
    app.add_handler(CommandHandler("panel", on_panel))
    app.add_handler(CommandHandler("cancel", on_cancel))
    app.add_handler(CallbackQueryHandler(on_menu_callback, pattern=r"^menu:"))
    app.add_handler(CallbackQueryHandler(on_panel_callback, pattern=r"^panel:"))
    app.add_handler(CallbackQueryHandler(on_mod_callback, pattern=r"^mod:"))
    app.add_handler(CallbackQueryHandler(on_modundo_callback, pattern=r"^modundo:"))
    app.add_handler(CallbackQueryHandler(on_aiundo_callback, pattern=r"^aiundo:"))
    app.add_handler(CallbackQueryHandler(on_captcha_callback, pattern=r"^cap:"))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_new_members))
    app.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, on_left_member))
    app.add_handler(CallbackQueryHandler(on_burn_callback, pattern=r"^burn:"))
    app.add_handler(CallbackQueryHandler(on_gov_callback, pattern=r"^gov:"))
    app.add_handler(CallbackQueryHandler(on_lang_callback, pattern=r"^lang:"))
    app.add_handler(CallbackQueryHandler(on_pick_callback, pattern=r"^pick:"))
    app.add_handler(CallbackQueryHandler(on_game_callback))
    app.add_handler(InlineQueryHandler(on_inline_query))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    app.add_handler(MessageHandler(filters.UpdateType.EDITED_MESSAGE & filters.TEXT & ~filters.COMMAND, on_edited_message))
    app.add_handler(MessageHandler((filters.PHOTO | filters.VIDEO | filters.ANIMATION | filters.Document.ALL | filters.AUDIO | filters.VOICE) & ~filters.COMMAND, on_media_message))
    if app.job_queue:
        app.job_queue.run_repeating(job_burn_check, interval=3600, first=120)
        app.job_queue.run_repeating(job_gov_check, interval=1800, first=180)
        app.job_queue.run_repeating(job_validator_check, interval=3600, first=240)
        app.job_queue.run_repeating(job_pr_check, interval=300, first=260)
        app.job_queue.run_repeating(job_captcha_sweep, interval=60, first=30)
        app.job_queue.run_repeating(job_fresh_sweep, interval=600, first=90)
        app.job_queue.run_repeating(job_scam_alerts, interval=1800, first=300)
        app.job_queue.run_repeating(job_usage_report, interval=900, first=420)  # owner daily usage DM, 7 PM ET (self-healing check inside)
        import datetime as _dt
        app.job_queue.run_daily(job_burn_daily, time=_dt.time(hour=1, minute=0))  # ~9pm ET (UTC-4), shifts 1h in winter
    print("LUNC Assistant Bot polling…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
