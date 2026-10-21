# LUNC Assistant Bot

Full AI assistant for Telegram groups. Main job: turn hundreds of group messages into a quick summary.

**Display name:** LUNC Assistant Bot
**Suggested username:** @LUNCAssistantBot (must end in `bot` — if taken, try @LUNCAssistant_AIBot, tell Tom the final one)

## Commands
/summary, /summary 300, /summary 24h, /summary detailed, /catchup, /tldr (reply), /ask, /proposal <id>, /price, /burn, /burnalerts, /settings, /help
DM the bot with a long pasted/forwarded text = instant summary.

## Owner Setup — only 2 things only you can do
Bot creation and tokens live in your accounts, Tom builds/deploys everything else.

### 1. Create the bot in BotFather (2 minutes, in Telegram)
1. Open @BotFather > /newbot
2. Name: `LUNC Assistant Bot`
3. Username: `LUNCAssistantBot` (or variant if taken)
4. BotFather gives you a token — DO NOT send it in chat. Keep it for Railway step.
5. Then in BotFather: /mybots > LUNC Assistant Bot > Bot Settings > Group Privacy > **Turn off**
   (Or just make the bot Admin in your test group — that also lets it see messages. Doing both is best.)

### 2. Railway deploy (Tom prepares repo, you paste secrets)
- New Railway project from this repo (lunc-projects/lunc-assistant-bot)
- Variables: TELEGRAM_BOT_TOKEN (from BotFather), AI_API_KEY
  - Cheapest start: Groq free key at console.groq.com + AI_BASE_URL=https://api.groq.com/openai/v1 + AI_MODEL=llama-3.1-8b-instant
  - Or OpenAI key + defaults
- Start command is in Procfile: `python bot.py`

### 3. Test group
- Add bot to your test group, promote to Admin, send a few messages, then /summary

## Limits
- Bot only sees messages after it joins. No pre-join history via Bot API.
- Without AI_API_KEY it still works in fallback mode (stats/links/recent messages), AI summaries turn on when key is added.
- Messages stored locally 7 days rolling (RETENTION_DAYS), only text/name/time.

## Files
bot.py (main), store.py (SQLite log), ai_client.py (AI + fallback), kb.py (verified project KB)

## Burn notifications (opt-in, default OFF)
- `/burnalerts` opens a tap-button menu: master ON/OFF + 3 types — Daily burn report (~9pm ET), Big burns (supply drop >= 100M LUNC between hourly checks, threshold in env BIG_BURN_THRESHOLD_LUNC), Burn tax rate changes (polled hourly from LCD).
- Also `/burnalerts on` / `/burnalerts off`. In groups only admins can change it; in DM it's personal.
- `/burn` anytime = live burn tax rate (verified live endpoint returns burn_tax_rate 0.015) + explainer.

## Full Top Pack (added 2026-10-21, owner picked "all 5" + voting/proposals + validator watch)
- Live info: /price (LUNC+USTC, mcap, volume), /stats, /convert, /proposals, /proposal <id> (now with live tally), /burn
- Lookups: /wallet terra1... (public balances + staking), /token terra1... (CW20 token_info + safety warning)
- Validators: /validators (top 10), /validator <name|valoper>
- Staking: /stake guide, /calc estimate (scenario table, labelled estimate — no fake APR)
- Info: /links, /safety, /learn <word>
- Proposal/voting alerts: /govalerts tap-menu, master OFF by default + New / Ending <24h / Result. Job polls every 30 min.
- Validator watch: /watchvalidator <name|valoper> per chat, /unwatchvalidator, /watchlist. Hourly job alerts on jail, status, commission change, or voting-power move >5%. Generic — watch ANY validator, none pre-seeded.
- Honest limit: bot does NOT report individual validator votes — the public LCD votes list endpoint is unreliable (returned empty for known voted proposals before), so it never claims a validator did/didn't vote.
All endpoints (gov, tally, staking pool, validators, balances, CW20 smart query, CoinGecko) verified live 2026-10-21.
