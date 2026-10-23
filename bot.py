#!/usr/bin/env python3
"""LUNC Assistant Bot — full AI assistant for Telegram groups.
Core: summarize hundreds of messages into a quick summary.
Also: /catchup, /tldr, /ask (general AI Q&A), DM summary. Standalone — no other projects included.
Run: TELEGRAM_BOT_TOKEN=... AI_API_KEY=... python bot.py
"""
import os, re, time, json, datetime, pathlib
import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
import store, ai_client, burn as burn_mod, chain
from kb import kb_as_text, find_kb_answer

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
OWNER_ID = int(os.getenv("OWNER_TELEGRAM_ID", "0") or 0)
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
/safety — scam / seed phrase safety rules
/learn <word> — plain-English glossary (e.g. /learn quorum)

*Notifications (your choice, on/off)*
/burnalerts — burn notifications menu (master on/off + types)
/govalerts — proposal / voting notifications menu (new, ending soon, result)
/watchvalidator <name or terravaloper...> — watch a validator in this chat
/unwatchvalidator <terravaloper...> — stop watching
/watchlist — validators watched in this chat
/settings — notification menus hub
In a group, only admins can change group settings. In DM, it's just for you.

*Other*
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
        await update.message.reply_text(text[i:i+3900])

async def on_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP, parse_mode=ParseMode.MARKDOWN)

async def on_summary(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    rows, detailed = parse_summary_args(ctx.args, update.effective_chat.id)
    if not rows:
        await update.message.reply_text("No messages logged yet — I can only summarize messages sent after I joined this group. Give it some activity, then try /summary again.")
        return
    await update.message.reply_text(f"Summarizing {len(rows)} messages…")
    out = await ai_client.summarize(rows, detailed=detailed)
    await send_long(update, out)
    store.set_catchup(update.effective_chat.id, update.effective_user.id)

async def on_catchup(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid, uid = update.effective_chat.id, update.effective_user.id
    last = store.get_catchup_id(cid, uid)
    if last is None:
        rows = store.get_messages(cid, limit=200)
        await update.message.reply_text("First catchup — here's the last 200, and I'll track from here next time.")
    else:
        rows = store.get_messages(cid, limit=1000, after_id=last)
    if not rows:
        await update.message.reply_text("You're all caught up — no new messages since your last /catchup.")
        return
    out = await ai_client.summarize(rows)
    await send_long(update, f"📬 Catchup — {len(rows)} new messages\n\n{out}")
    store.set_catchup(cid, uid)

async def on_tldr(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message.reply_to_message
    if not msg or not msg.text:
        await update.message.reply_text("Reply to a long message with /tldr and I'll shrink it.")
        return
    out = await ai_client.chat([
        {"role":"system","content":"Summarize the message in 2-3 short lines. No extra commentary."},
        {"role":"user","content": msg.text}]) or msg.text[:400]
    await update.message.reply_text(f"⚡ TL;DR: {out}")

async def on_ask(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = " ".join(ctx.args).strip()
    if not q:
        await update.message.reply_text("Ask me something: /ask explain this proposal in simple words")
        return
    out = await ai_client.chat([
        {"role":"system","content":"You are LUNC Assistant Bot, a standalone general AI assistant for Telegram groups. Answer clearly and concisely. Do not invent contract addresses or claim knowledge of any specific project."},
        {"role":"user","content": q}])
    if not out:
        out = "AI isn't configured yet (no AI_API_KEY). The owner can add the key in Railway and I'll answer fully."
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
    await update.message.reply_text(burn_mod.burn_explainer(rate), parse_mode=ParseMode.MARKDOWN)

async def on_burnalerts(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    if ctx.args and ctx.args[0].lower() in ("on", "off"):
        if not await _can_change(update, ctx):
            await update.message.reply_text("Only group admins can change this group's settings."); return
        store.set_setting(cid, "burn_alerts", ctx.args[0].lower())
    kb, _ = burn_keyboard(cid)
    await update.message.reply_text(burn_status_text(cid), reply_markup=kb, parse_mode=ParseMode.MARKDOWN)

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
async def on_price2(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        d = await chain.prices()
        msg = "💰 *Prices — live (CoinGecko)*\n" + chain.fmt_price(d["terra-luna"], "LUNC") + "\n" + chain.fmt_price(d["terrausd"], "USTC")
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
    except Exception:
        await update.message.reply_text("Couldn't fetch prices right now.")

async def on_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try: await update.message.reply_text(await chain.stats_text(), parse_mode=ParseMode.MARKDOWN)
    except Exception: await update.message.reply_text("Couldn't fetch chain stats right now.")

async def on_convert(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Usage: /convert 1000000  (LUNC amount)  or  /convert 10 usd"); return
    try:
        amt = float(ctx.args[0].replace(",", "")); d = await chain.prices(); price = d["terra-luna"]["usd"]
        if len(ctx.args) > 1 and ctx.args[1].lower() == "usd":
            await update.message.reply_text(f"${amt:,.2f} ≈ {amt/price:,.0f} LUNC (at ${price:.8g}, CoinGecko)")
        else:
            await update.message.reply_text(f"{amt:,.0f} LUNC ≈ ${amt*price:,.2f} (at ${price:.8g}, CoinGecko)")
    except Exception: await update.message.reply_text("Couldn't convert right now — check the amount format.")

async def on_proposals(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        props = await chain.proposals_voting()
    except Exception:
        await update.message.reply_text("Couldn't fetch proposals right now."); return
    if not props:
        await update.message.reply_text("No proposals are in the voting period right now."); return
    lines = ["🗳️ *Proposals currently voting:*"]
    for pr in props:
        lines.append(f"\n*{pr['id']}* — {pr.get('title','(no title)')}\nVoting ends: {pr.get('voting_end_time','')} UTC\nUse /proposal {pr['id']} for the tally")
    await send_long(update, "\n".join(lines))

async def on_wallet(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args: await update.message.reply_text("Usage: /wallet terra1..."); return
    try: await update.message.reply_text(await chain.wallet_text(ctx.args[0]), parse_mode=ParseMode.MARKDOWN)
    except Exception: await update.message.reply_text("Couldn't fetch that wallet right now.")

async def on_token(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args: await update.message.reply_text("Usage: /token terra1... (CW20 contract)"); return
    await update.message.reply_text(await chain.token_text(ctx.args[0]), parse_mode=ParseMode.MARKDOWN)

async def on_validators(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        vals = await chain.validators_top(10)
        lines = ["🏛️ *Top 10 validators by voting power*"]
        for i, v in enumerate(vals, 1):
            lines.append(f"{i}. {v['description']['moniker']} — {int(v['tokens'])/1e6:,.0f} LUNC, commission {float(v['commission']['commission_rates']['rate'])*100:.1f}%")
        lines.append("\nDetail: /validator <name>   Watch one: /watchvalidator <name>")
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
    except Exception: await update.message.reply_text("Couldn't fetch validators right now.")

async def on_validator_info(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args: await update.message.reply_text("Usage: /validator <moniker or terravaloper...>"); return
    try:
        v = await chain.find_validator(" ".join(ctx.args))
        if not v: await update.message.reply_text("Validator not found — check the name or use the terravaloper address."); return
        await update.message.reply_text(chain.validator_text(v), parse_mode=ParseMode.MARKDOWN)
    except Exception: await update.message.reply_text("Couldn't fetch that validator right now.")

STAKE_TEXT = """🥩 *How LUNC staking works*
1. Hold LUNC in a wallet you control (Galaxy Station, Keplr, Leap).
2. Pick a validator — check commission, uptime, and voting record (/validators). Smaller validators help decentralisation.
3. Delegate (stake) your LUNC to them. You can split across validators.
4. You earn rewards in LUNC; claim them in your wallet app.
5. Unbonding takes *21 days* — during that time LUNC earns nothing and can't move.
6. Redelegating moves stake to another validator instantly (then a 21-day cooldown for that amount).
Risks: validator downtime/slashing can cost a small %; price can move while unbonding. This is info, not financial advice."""

async def on_stake(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(STAKE_TEXT, parse_mode=ParseMode.MARKDOWN)

async def on_calc(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args: await update.message.reply_text("Usage: /calc 1000000 — reward estimate for staking that many LUNC for 1 year"); return
    try:
        amt = float(ctx.args[0].replace(",", ""))
        # Estimate only: bonded ratio method is complex on-chain; use a clearly-labelled range via supply inflation proxy is unreliable,
        # so present a simple scenario table instead of a fake precise APR.
        lines = [f"🧮 *Reward ESTIMATE for {amt:,.0f} LUNC over 1 year* (before validator commission, not a promise):"]
        for apr in (5, 10, 15, 20):
            lines.append(f"• At {apr}% APR: ~{amt*apr/100:,.0f} LUNC")
        lines.append("Actual APR moves with staking ratio, tax, and commission — check your wallet app for the live rate before staking.")
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
    except Exception: await update.message.reply_text("Check the amount — example: /calc 1000000")

LINKS_TEXT = """🔗 *Official links only*
Terra Classic: https://terra-classic.io (community)
Block explorer / Finder: https://finder.terra.money/classic
Galaxy Station wallet: https://station.terraclassic.community
Keplr wallet: https://www.keplr.app
LUNCDash: https://luncdash.com
Governance forum: https://discuss.terra-classic.io (verify current forum in chat)
Terra Classic docs / GitHub: https://github.com/classic-terra
CoinGecko LUNC: https://www.coingecko.com/en/coins/terra-luna
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

async def on_links(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(LINKS_TEXT, parse_mode=ParseMode.MARKDOWN)

async def on_safety(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(SAFETY_TEXT, parse_mode=ParseMode.MARKDOWN)

async def on_learn(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Usage: /learn <word> — try: " + ", ".join(GLOSSARY.keys())); return
    w = " ".join(ctx.args).lower()
    if w in GLOSSARY: await update.message.reply_text(f"📖 *{w}*: {GLOSSARY[w]}", parse_mode=ParseMode.MARKDOWN); return
    out = await ai_client.chat([{"role":"system","content":"Explain the crypto/Terra Classic term in 2-3 plain lines for a beginner. No financial advice."},{"role":"user","content":w}])
    await update.message.reply_text(out or "I don't have that one yet — try /learn quorum")

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
            await update.message.reply_text("Only group admins can change this group's settings."); return
        store.set_setting(cid, "gov_alerts", ctx.args[0].lower())
    await update.message.reply_text(gov_status_text(cid), reply_markup=gov_keyboard(cid), parse_mode=ParseMode.MARKDOWN)

async def on_gov_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not await _can_change(update, ctx):
        await q.answer("Only group admins can change group settings.", show_alert=True); return
    key = q.data.split(":", 1)[1]; cid = q.message.chat.id
    cur = store.get_setting(cid, key); store.set_setting(cid, key, "off" if cur == "on" else "on")
    await q.answer(f"{key}: {'OFF' if cur=='on' else 'ON'}")
    await q.edit_message_text(gov_status_text(cid), reply_markup=gov_keyboard(cid), parse_mode=ParseMode.MARKDOWN)

async def on_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⚙️ *Settings — notifications are your choice*\n🔥 /burnalerts — burn notifications\n🗳️ /govalerts — proposal & voting notifications\n🏛️ /watchlist — validators watched in this chat", parse_mode=ParseMode.MARKDOWN)

# ================= VALIDATOR WATCH =================
async def on_watchvalidator(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args: await update.message.reply_text("Usage: /watchvalidator <moniker or terravaloper...>"); return
    try:
        v = await chain.find_validator(" ".join(ctx.args))
        if not v: await update.message.reply_text("Validator not found."); return
        store.watch_validator(update.effective_chat.id, v["operator_address"], v["description"]["moniker"], json.dumps(chain.snapshot(v)))
        await update.message.reply_text(f"👀 Watching *{v['description']['moniker']}* in this chat.\nI'll alert here if it gets jailed, changes status or commission, or its voting power moves >5%.", parse_mode=ParseMode.MARKDOWN)
    except Exception: await update.message.reply_text("Couldn't add that validator right now.")

async def on_unwatchvalidator(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args: await update.message.reply_text("Usage: /unwatchvalidator <terravaloper...> (see /watchlist)"); return
    n = store.unwatch_validator(update.effective_chat.id, ctx.args[0])
    await update.message.reply_text("Stopped watching that validator in this chat." if n else "That validator isn't on this chat's watchlist.")

async def on_watchlist(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    rows = store.list_watched(update.effective_chat.id)
    if not rows: await update.message.reply_text("No validators watched in this chat yet. Add one: /watchvalidator <name>"); return
    lines = ["👀 *Watched in this chat:*"] + [f"• {r['moniker']} — {r['valoper']}" for r in rows]
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)

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
        await update.message.reply_text("Usage: /proposal 12234"); return
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
        await update.message.reply_text(f"Couldn't fetch proposal {pid} right now.")

async def on_price(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get("https://api.coingecko.com/api/v3/simple/price?ids=terra-luna&vs_currencies=usd&include_24hr_change=true"); r.raise_for_status()
            d = r.json()["terra-luna"]
        await update.message.reply_text(f"LUNC (Terra Classic): ${d['usd']} ({d.get('usd_24h_change',0):.2f}% 24h) — via CoinGecko, check live before trading.")
    except Exception:
        await update.message.reply_text("Couldn't fetch price right now.")

async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    chat, user, text = update.effective_chat, update.effective_user, update.message.text
    name = user.full_name + (f" (@{user.username})" if user.username else "")
    # Log group messages for summaries
    if chat.type in ("group", "supergroup"):
        store.log_message(chat.id, user.id, name, text, update.message.message_id)
    # Mention = ask
    bot_name = (await ctx.bot.get_me()).username
    if bot_name and f"@{bot_name}" in text:
        q = text.replace(f"@{bot_name}", "").strip()
        if q:
            ctx.args = q.split()
            # reuse ask logic with cleaned question: temporarily set message text path
            out = await ai_client.chat([
                {"role":"system","content":"You are LUNC Assistant Bot, a standalone general AI assistant. Answer clearly and concisely."},
                {"role":"user","content": q}]) or "AI isn't configured yet (no AI_API_KEY)." 
            await send_long(update, out)
        return
    # DM: any long text = summarize it
    if chat.type == "private" and len(text) > 600 and not text.startswith("/"):
        rows = [{"user_name": name, "text": text, "ts": int(time.time())}]
        out = await ai_client.summarize(rows)
        await send_long(update, out)

async def post_init(app: Application):
    try:
        await app.bot.set_my_description("LUNC Assistant Bot — I summarize busy group chats into a quick TL;DR and answer questions. Use /summary, /catchup, /ask in a group, or DM me a long text to summarize.")
        await app.bot.set_my_short_description("Summarizes hundreds of group messages into a quick summary + AI assistant.")
        await app.bot.set_my_commands([
            ("summary","Summarize group messages"),("catchup","What you missed"),("tldr","Shrink a message (reply to it)"),
            ("ask","Ask me anything"),("proposals","Proposals voting now"),("proposal","Proposal + tally"),("price","LUNC + USTC price"),("stats","Chain stats"),("burn","Live burn tax info"),("burnalerts","Burn notifications on/off"),("govalerts","Proposal alerts on/off"),("wallet","Public wallet lookup"),("token","CW20 token info"),("validators","Top validators"),("watchvalidator","Watch a validator"),("help","All commands")])
        # Profile photo (owner's logo) — re-applied on boot so redeploys never lose it
        try:
            from telegram import InputProfilePhotoStatic
            _pf = pathlib.Path(__file__).with_name("bot-profile-512.png")
            if _pf.exists():
                with open(_pf, "rb") as fh:
                    await app.bot.set_my_profile_photo(photo=InputProfilePhotoStatic(photo=fh.read()))
        except Exception as e:
            print(f"profile photo: {e}")
        print("LUNC Assistant Bot: description + commands set")
    except Exception as e:
        print(f"post_init: {e}")

def main():
    if not TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN is missing — paste it in Railway env vars (never in chat/repo).")
    _builder = Application.builder().token(TOKEN).post_init(post_init)
    _proxy = os.getenv("OUTBOUND_PROXY")
    if _proxy: _builder = _builder.proxy(_proxy).get_updates_proxy(_proxy)
    app = _builder.build()
    app.add_handler(CommandHandler("start", on_start))
    app.add_handler(CommandHandler("help", on_start))
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
    app.add_handler(CommandHandler("safety", on_safety))
    app.add_handler(CommandHandler("learn", on_learn))
    app.add_handler(CommandHandler("govalerts", on_govalerts))
    app.add_handler(CommandHandler("watchvalidator", on_watchvalidator))
    app.add_handler(CommandHandler("unwatchvalidator", on_unwatchvalidator))
    app.add_handler(CommandHandler("watchlist", on_watchlist))
    app.add_handler(CommandHandler("burnalerts", on_burnalerts))
    app.add_handler(CommandHandler("settings", on_settings))
    app.add_handler(CallbackQueryHandler(on_burn_callback, pattern=r"^burn:"))
    app.add_handler(CallbackQueryHandler(on_gov_callback, pattern=r"^gov:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    if app.job_queue:
        app.job_queue.run_repeating(job_burn_check, interval=3600, first=120)
        app.job_queue.run_repeating(job_gov_check, interval=1800, first=180)
        app.job_queue.run_repeating(job_validator_check, interval=3600, first=240)
        import datetime as _dt
        app.job_queue.run_daily(job_burn_daily, time=_dt.time(hour=1, minute=0))  # ~9pm ET (UTC-4), shifts 1h in winter
    print("LUNC Assistant Bot polling…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
