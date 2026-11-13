"""Tests for /aiban list mode (2026-11-13): the owner pastes
"/aiban @name1 @name2 …" (the command name he actually reaches
for) and every resolvable name gets FULL removal — the AI ban
AND the global ban together (see _list_ban full=True). Names
already carrying both bans are reported as such; a partial state
(AI-only or global-only) is completed. Non-owners are refused.
Single-target /aiban (reply or numeric, any moderator) keeps its
light-touch AI-only meaning exactly — asserted below.

Run: python3 test_aiban_list.py"""
import asyncio
import os
import sys
import tempfile
import types

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["OWNER_TELEGRAM_ID"] = "999"

# --- Dependency stubs (same pattern as test_gban_list.py) --------------
sys.modules.setdefault("httpx", types.ModuleType("httpx"))

tg = types.ModuleType("telegram")


class _Button:
    def __init__(self, text, callback_data=None, url=None, web_app=None, **_):
        self.text = text
        self.callback_data = callback_data
        self.url = url
        self.web_app = web_app


class _Markup:
    def __init__(self, inline_keyboard):
        self.inline_keyboard = inline_keyboard


class _Perms:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class _WebApp:
    def __init__(self, url):
        self.url = url


class _GameResult:
    def __init__(self, id, game_short_name):
        self.id = id
        self.game_short_name = game_short_name


tg.Update = object
tg.InlineKeyboardButton = _Button
tg.InlineKeyboardMarkup = _Markup
tg.ChatPermissions = _Perms
tg.WebAppInfo = _WebApp
tg.InlineQueryResultGame = _GameResult

constants = types.ModuleType("telegram.constants")
constants.ParseMode = types.SimpleNamespace(MARKDOWN="Markdown", HTML="HTML")
tg.constants = constants

error = types.ModuleType("telegram.error")


class _BadRequest(Exception):
    pass


error.BadRequest = _BadRequest
tg.error = error

ext = types.ModuleType("telegram.ext")


class _DummyHandler:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs


ext.Application = _DummyHandler
ext.CommandHandler = _DummyHandler
ext.MessageHandler = _DummyHandler
ext.CallbackQueryHandler = _DummyHandler
ext.InlineQueryHandler = _DummyHandler
ext.ContextTypes = types.SimpleNamespace(DEFAULT_TYPE=object)
ext.filters = types.SimpleNamespace()
tg.ext = ext

sys.modules["telegram"] = tg
sys.modules["telegram.constants"] = constants
sys.modules["telegram.error"] = error
sys.modules["telegram.ext"] = ext

import autoban
import bot
import store

OWNER, ELEV = 999, 777
BOT_ID = 4242
GROUP = -100222          # an approved protected group (ban target)
HOME = -100333           # the chat the commands are issued in

fails = []


def check(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        fails.append(name)


def user(uid, username=None, is_bot=False):
    return types.SimpleNamespace(id=uid, full_name=f"U{uid}", username=username,
                                 is_bot=is_bot)


def chat(cid):
    return types.SimpleNamespace(id=cid, type="supergroup", title="Chat")


class FakeMsg:
    def __init__(self, ch, usr, reply_to=None):
        self.chat, self.from_user = ch, usr
        self.reply_to_message = reply_to
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append(text)


class FakeBot:
    def __init__(self):
        self.id = BOT_ID
        self.bans = []

    async def ban_chat_member(self, chat_id, user_id):
        self.bans.append((chat_id, user_id))

    async def unban_chat_member(self, chat_id, user_id, only_if_banned=False):
        pass

    async def get_chat_member(self, chat_id, user_id):
        return types.SimpleNamespace(status="member")

    async def send_message(self, chat_id, text, **kwargs):
        pass


def upd(msg, usr):
    return types.SimpleNamespace(
        message=msg, effective_message=msg,
        effective_chat=msg.chat, effective_user=usr)


def ctx(fb, args):
    return types.SimpleNamespace(bot=fb, args=args)


# --- Seed: one approved protected group + the bot's own records. -----
# Same stored user_name format as test_gban_list.py.
store.mod_request_group(GROUP, "Protected Group", OWNER)
store.mod_approve_group(GROUP)
store.elevated_add(ELEV, OWNER)
store.log_message(GROUP, 555, "YL Payment (@YLzhangwei888)", "ad one", 1)
store.log_message(GROUP, 556, "ylpay158", "ad two", 2)          # display-name only
store.log_message(GROUP, 557, "Old News (@OldBanned)", "old spam", 3)
store.log_message(GROUP, 558, "Gban Only (@GbanOnly)", "ad three", 4)
store.log_message(GROUP, 559, "Ai Only (@AiOnly)", "ad four", 5)
store.log_message(GROUP, OWNER, "The Owner (@OwnerHandle)", "hi", 6)
store.log_message(GROUP, BOT_ID, "Lunc Assistant (@LuncAssistantBot)", "beep", 7)
store.log_message(GROUP, 560, "Late Scam (@LateScam)", "ad five", 8)
# Pre-existing ban states the mixed list must handle appropriately:
store.gban_add(557, "earlier gban", OWNER)                       # 557: BOTH bans
store.ai_ban_add(557, "earlier ai ban", OWNER)
store.gban_add(558, "earlier gban", OWNER)                       # 558: global only
store.ai_ban_add(559, "earlier ai ban", OWNER)                   # 559: AI only


async def main():
    # --- The mixed list. ----------------------------------------------
    fb = FakeBot()
    cmd = FakeMsg(chat(HOME), user(OWNER))
    await bot.on_aiban(upd(cmd, user(OWNER)), ctx(fb, [
        "@YLzhangwei888", "@ylpay158", "@OldBanned", "@GbanOnly",
        "@AiOnly", "@OwnerHandle", "@LuncAssistantBot", "@NeverSeenBot",
        "@ylzhangwei888"]))
    check("list: clean name gets BOTH bans with the default reason",
          store.ai_ban_get(555) is not None
          and store.ai_ban_get(555)["reason"] == "global list ban"
          and store.ai_ban_get(555)["banned_by"] == OWNER
          and store.gban_get(555) is not None
          and store.gban_get(555)["reason"] == "global list ban"
          and store.gban_get(555)["banned_by"] == OWNER)
    check("list: clean name removed from the protected group",
          (GROUP, 555) in fb.bans)
    check("list: display-matched name gets BOTH bans + group removal",
          store.ai_ban_get(556) is not None
          and store.gban_get(556) is not None
          and (GROUP, 556) in fb.bans)
    check("list: fully-banned name untouched (reasons kept, no re-ban)",
          store.gban_get(557)["reason"] == "earlier gban"
          and store.ai_ban_get(557)["reason"] == "earlier ai ban"
          and (GROUP, 557) not in fb.bans)
    check("list: global-only state completed with the AI ban",
          store.ai_ban_get(558) is not None
          and store.ai_ban_get(558)["reason"] == "global list ban")
    check("list: global-only name NOT re-applied to the group",
          store.gban_get(558)["reason"] == "earlier gban"
          and (GROUP, 558) not in fb.bans)
    check("list: AI-only state completed with the global ban + removal",
          store.gban_get(559) is not None
          and store.gban_get(559)["reason"] == "global list ban"
          and store.ai_ban_get(559)["reason"] == "earlier ai ban"
          and (GROUP, 559) in fb.bans)
    check("list: owner never banned", store.gban_get(OWNER) is None
          and store.ai_ban_get(OWNER) is None)
    check("list: the bot itself never banned",
          store.gban_get(BOT_ID) is None and store.ai_ban_get(BOT_ID) is None)
    expected = (
        "🚫 List ban done.\n"
        "Banned 4: @YLzhangwei888, @ylpay158 *, @GbanOnly, @AiOnly\n"
        "* matched on display name only — no @username on record for them.\n"
        "Already banned: @OldBanned\n"
        "Skipped (you / the bot): @OwnerHandle, @LuncAssistantBot\n"
        "Not found: @NeverSeenBot — never seen by this bot, can't ban by "
        "name; the auto-ban catches them if they ever post.")
    check("list: reply is exact", cmd.replies == [expected])
    ai_rows = [r for r in store.mod_log_recent(20)
               if r["action"] == "aiban" and "list ban:" in (r["detail"] or "")]
    gb_rows = [r for r in store.mod_log_recent(20)
               if r["action"] == "gban" and "list ban:" in (r["detail"] or "")]
    check("list: mod_log has one aiban row per newly AI-banned (555/556/558)",
          sorted(r["target"] for r in ai_rows) == [555, 556, 558])
    check("list: mod_log has one gban row per newly globally banned (555/556/559)",
          sorted(r["target"] for r in gb_rows) == [555, 556, 559])

    # --- Non-owner (elevated) list attempt is refused. ----------------
    fb2 = FakeBot()
    cmd2 = FakeMsg(chat(HOME), user(ELEV))
    await bot.on_aiban(upd(cmd2, user(ELEV)), ctx(fb2, ["@LateScam"]))
    check("list: non-owner refused with the exact line",
          cmd2.replies == ["Owner only for list bans."])
    check("list: non-owner attempt banned nobody",
          store.ai_ban_get(560) is None and store.gban_get(560) is None
          and fb2.bans == [])

    # --- Words after the list become the reason for BOTH bans. --------
    fb3 = FakeBot()
    cmd3 = FakeMsg(chat(HOME), user(OWNER))
    await bot.on_aiban(upd(cmd3, user(OWNER)),
                       ctx(fb3, ["@LateScam", "scam", "network"]))
    check("list: appended words become the reason for BOTH bans",
          store.ai_ban_get(560) is not None
          and store.ai_ban_get(560)["reason"] == "scam network"
          and store.gban_get(560) is not None
          and store.gban_get(560)["reason"] == "scam network"
          and (GROUP, 560) in fb3.bans)
    check("list: single-name reply has no empty sections",
          cmd3.replies == ["🚫 List ban done.\nBanned 1: @LateScam"])

    # --- Single-target /aiban unchanged: AI-only, no gban side effect.
    fb4 = FakeBot()
    cmd4 = FakeMsg(chat(HOME), user(ELEV))
    await bot.on_aiban(upd(cmd4, user(ELEV)), ctx(fb4, ["561", "spammy"]))
    check("single: numeric /aiban by a moderator AI-bans only",
          store.ai_ban_get(561) is not None
          and store.ai_ban_get(561)["reason"] == "spammy"
          and store.gban_get(561) is None
          and (GROUP, 561) not in fb4.bans)
    check("single: numeric /aiban keeps its reply wording",
          len(cmd4.replies) == 1 and "is AI-banned" in cmd4.replies[0])

    target = FakeMsg(chat(HOME), user(562))
    cmd5 = FakeMsg(chat(HOME), user(OWNER), reply_to=target)
    await bot.on_aiban(upd(cmd5, user(OWNER)), ctx(FakeBot(), []))
    check("single: reply-target /aiban AI-bans only",
          store.ai_ban_get(562) is not None
          and store.gban_get(562) is None)

    # A reply-ban whose reason mentions an @name must NOT be hijacked
    # into list mode: the reply target wins, as _mod_target rules.
    target2 = FakeMsg(chat(HOME), user(563))
    cmd6 = FakeMsg(chat(HOME), user(OWNER), reply_to=target2)
    await bot.on_aiban(upd(cmd6, user(OWNER)),
                       ctx(FakeBot(), ["@SomeName", "crew"]))
    check("single: reply + @mention reason AI-bans the reply target only",
          store.ai_ban_get(563) is not None
          and store.ai_ban_get(563)["reason"] == "@SomeName crew"
          and store.gban_get(563) is None)
    check("single: reply + @mention reason keeps single-ban wording",
          len(cmd6.replies) == 1 and "is AI-banned" in cmd6.replies[0])


asyncio.run(main())
TOTAL = 21
print(f"\n{TOTAL - len(fails)}/{TOTAL} passed" if not fails
      else f"\nFAILED: {fails}")
sys.exit(1 if fails else 0)
