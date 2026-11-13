"""Tests for /gban list mode (2026-11-13): the owner pastes a
list of @usernames and every name the bot can resolve from its
own message log (store.resolve_username) gets the normal global
ban; already-banned, owner/bot and never-seen names are reported
back in sections. Non-owners are refused. Single-target /gban
(numeric and reply) is unchanged.

Run: python3 test_gban_list.py"""
import asyncio
import os
import sys
import tempfile
import types

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["OWNER_TELEGRAM_ID"] = "999"

# --- Dependency stubs (same pattern as test_del.py / test_filter.py) ---
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
# messages.user_name holds "Full Name (@handle)", or just the display
# name when the user has no @username (bot.py on_message) — the seeds
# below use exactly that stored format.
store.mod_request_group(GROUP, "Protected Group", OWNER)
store.mod_approve_group(GROUP)
store.elevated_add(ELEV, OWNER)
store.log_message(GROUP, 555, "YL Payment (@YLzhangwei888)", "ad one", 1)
store.log_message(GROUP, 556, "ylpay158", "ad two", 2)          # display-name only
store.log_message(GROUP, 557, "Old News (@OldBanned)", "old spam", 3)
store.log_message(GROUP, OWNER, "The Owner (@OwnerHandle)", "hi", 4)
store.log_message(GROUP, BOT_ID, "Lunc Assistant (@LuncAssistantBot)", "beep", 5)
store.log_message(GROUP, 558, "Second Scam (@SecondScam)", "ad three", 6)
store.log_message(GROUP, 559, "Third Scam (@ThirdScam)", "ad four", 7)
store.gban_add(557, "earlier ban", OWNER)                        # already banned

# --- Resolver unit checks ---------------------------------------------
check("resolver: username match, case-insensitive",
      store.resolve_username("ylzhangwei888") == (555, "username"))
check("resolver: username match, mixed case input",
      store.resolve_username("YLZHANGWEI888") == (555, "username"))
check("resolver: display-name match labelled as such",
      store.resolve_username("YLPAY158") == (556, "display"))
check("resolver: never-seen name -> None",
      store.resolve_username("ghosthandle") is None)
check("resolver: empty -> None", store.resolve_username("") is None)


async def main():
    # --- The mixed list: 2 resolvable + already-banned + owner + bot
    # + 1 unknown + a case-variant duplicate. -------------------------
    fb = FakeBot()
    cmd = FakeMsg(chat(HOME), user(OWNER))
    await bot.on_gban(upd(cmd, user(OWNER)), ctx(fb, [
        "@YLzhangwei888", "@ylpay158", "@OldBanned", "@OwnerHandle",
        "@LuncAssistantBot", "@NeverSeenBot", "@ylzhangwei888"]))
    check("list: username-matched user globally banned",
          store.gban_get(555) is not None
          and store.gban_get(555)["reason"] == "global list ban"
          and store.gban_get(555)["banned_by"] == OWNER)
    check("list: display-matched user globally banned",
          store.gban_get(556) is not None)
    check("list: bans applied in the protected group",
          (GROUP, 555) in fb.bans and (GROUP, 556) in fb.bans)
    check("list: already-banned user untouched (reason kept, no re-ban)",
          store.gban_get(557)["reason"] == "earlier ban"
          and (GROUP, 557) not in fb.bans)
    check("list: owner never banned", store.gban_get(OWNER) is None)
    check("list: the bot itself never banned", store.gban_get(BOT_ID) is None)
    expected = (
        "🚫 List ban done.\n"
        "Banned 2: @YLzhangwei888, @ylpay158 *\n"
        "* matched on display name only — no @username on record for them.\n"
        "Already banned: @OldBanned\n"
        "Skipped (you / the bot): @OwnerHandle, @LuncAssistantBot\n"
        "Not found: @NeverSeenBot — never seen by this bot, can't ban by "
        "name; the auto-ban catches them if they ever post.")
    check("list: reply is exact", cmd.replies == [expected])
    rows = [r for r in store.mod_log_recent(10) if r["action"] == "gban"]
    check("list: one mod_log row per new ban, with the typed name",
          len(rows) == 2
          and all("list ban:" in (r["detail"] or "") for r in rows))

    # --- Words after the list become the reason. ----------------------
    fb2 = FakeBot()
    cmd2 = FakeMsg(chat(HOME), user(OWNER))
    await bot.on_gban(upd(cmd2, user(OWNER)),
                      ctx(fb2, ["@SecondScam", "scam", "network"]))
    check("list: appended words become the ban reason",
          store.gban_get(558) is not None
          and store.gban_get(558)["reason"] == "scam network")
    check("list: single-name reply has no empty sections",
          cmd2.replies == ["🚫 List ban done.\nBanned 1: @SecondScam"])

    # --- Non-owner (elevated) list attempt is refused. ----------------
    fb3 = FakeBot()
    cmd3 = FakeMsg(chat(HOME), user(ELEV))
    await bot.on_gban(upd(cmd3, user(ELEV)), ctx(fb3, ["@ThirdScam"]))
    check("list: non-owner refused with the exact line",
          cmd3.replies == ["Owner only for list bans."])
    check("list: non-owner attempt banned nobody",
          store.gban_get(559) is None and fb3.bans == [])

    # --- Single-target paths unchanged. -------------------------------
    fb4 = FakeBot()
    cmd4 = FakeMsg(chat(HOME), user(OWNER))
    await bot.on_gban(upd(cmd4, user(OWNER)), ctx(fb4, ["560", "spam"]))
    check("single: numeric /gban still bans",
          store.gban_get(560) is not None
          and store.gban_get(560)["reason"] == "spam"
          and (GROUP, 560) in fb4.bans)
    check("single: numeric /gban keeps its reply wording",
          len(cmd4.replies) == 1 and "now globally banned" in cmd4.replies[0])

    target = FakeMsg(chat(HOME), user(561))
    cmd5 = FakeMsg(chat(HOME), user(OWNER), reply_to=target)
    await bot.on_gban(upd(cmd5, user(OWNER)), ctx(FakeBot(), []))
    check("single: reply-target /gban still bans",
          store.gban_get(561) is not None)

    # A reply-ban whose reason mentions an @name must NOT be hijacked
    # into list mode: the reply target wins, as _mod_target rules.
    target2 = FakeMsg(chat(HOME), user(562))
    cmd6 = FakeMsg(chat(HOME), user(OWNER), reply_to=target2)
    await bot.on_gban(upd(cmd6, user(OWNER)),
                      ctx(FakeBot(), ["@SomeName", "crew"]))
    check("single: reply + @mention reason bans the reply target",
          store.gban_get(562) is not None
          and store.gban_get(562)["reason"] == "@SomeName crew")
    check("single: reply + @mention reason keeps single-ban wording",
          len(cmd6.replies) == 1 and "now globally banned" in cmd6.replies[0])


asyncio.run(main())
TOTAL = 22
print(f"\n{TOTAL - len(fails)}/{TOTAL} passed" if not fails
      else f"\nFAILED: {fails}")
sys.exit(1 if fails else 0)
