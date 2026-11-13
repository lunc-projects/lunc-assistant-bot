"""Tests for the permanent name blocklist (2026-11-13): @usernames
filed by name (store.name_blocklist) are banned ON SIGHT — the usage
observer checks the ACTING user's own @username on every sighting in
any chat (group post, DM, button tap), captures the id permanently,
and lands the full strike (global ban + AI ban + group removal +
message deleted + owner DM with the report button). Filing routes:
owner /blockname (multi-name paste), /unblockname, /blocklist, and
the not-found names of an owner /gban or /aiban list ban, which are
filed automatically. Message TEXT naming a blocked account never
triggers anything; owner and bot are immune.

Run: python3 test_blocklist.py"""
import asyncio
import os
import sys
import tempfile
import types

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["OWNER_TELEGRAM_ID"] = "999"

# --- Dependency stubs (same pattern as test_gban_list.py) ---
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

import bot
import store

OWNER, ELEV = 999, 777
BOT_ID = 4242
PROTECTED = -100222      # an approved protected group (propagation target)
GROUP = -100555          # an ordinary supergroup the bot serves
TITLE = "Terra Luna Classic Chat"

fails = []


def check(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        fails.append(name)


def user(uid, username=None, is_bot=False):
    return types.SimpleNamespace(id=uid, full_name=f"U{uid}", username=username,
                                 is_bot=is_bot)


def chat(cid, ctype="supergroup", title=TITLE):
    return types.SimpleNamespace(id=cid, type=ctype, title=title)


class FakeMsg:
    def __init__(self, ch, usr, text="", mid=1):
        self.chat, self.from_user = ch, usr
        self.text = text
        self.message_id = mid
        self.entities = []
        self.reply_to_message = None
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append(text)


class FakeBot:
    def __init__(self):
        self.id = BOT_ID
        self.bans = []
        self.deleted = []
        self.sent = []          # (chat_id, text, kwargs)

    async def ban_chat_member(self, chat_id, user_id):
        self.bans.append((chat_id, user_id))

    async def unban_chat_member(self, chat_id, user_id, only_if_banned=False):
        pass

    async def delete_message(self, chat_id, message_id):
        self.deleted.append((chat_id, message_id))

    async def get_chat_member(self, chat_id, user_id):
        return types.SimpleNamespace(status="member")

    async def get_me(self):
        return types.SimpleNamespace(username="LuncAssistantBot")

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append((chat_id, text, kwargs))


def upd(msg, usr):
    return types.SimpleNamespace(
        message=msg, effective_message=msg,
        effective_chat=msg.chat, effective_user=usr, edited_message=None)


def ctx(fb, args=()):
    return types.SimpleNamespace(bot=fb, args=list(args))


def owner_dms(fb):
    return [s for s in fb.sent if s[0] == OWNER]


# One approved protected group (the _apply_gban propagation target).
store.mod_request_group(PROTECTED, "Protected Group", OWNER)
store.mod_approve_group(PROTECTED)

# --- Store-level units -------------------------------------------------
check("store: add normalizes case and @, returns True",
      store.blockname_add("@YLzhangwei888", OWNER, "scam network") is True)
check("store: duplicate add returns False, original kept",
      store.blockname_add("ylzhangwei888", ELEV, "other") is False
      and store.blockname_get("ylzhangwei888")["reason"] == "scam network"
      and store.blockname_get("@YLZHANGWEI888")["added_by"] == OWNER)
check("store: hit pairing records once per account",
      store.blockname_hit("ylzhangwei888", 5555) is True
      and store.blockname_hit("ylzhangwei888", 5555) is False
      and store.blockname_hit("ylzhangwei888", 5556) is True)
_row = [r for r in store.blockname_all() if r["username"] == "ylzhangwei888"]
check("store: blockname_all carries the hit count",
      len(_row) == 1 and _row[0]["hits"] == 2)
check("store: remove round-trip",
      store.blockname_add("temphandle", OWNER, "") is True
      and store.blockname_remove("@TempHandle") == 1
      and store.blockname_get("temphandle") is None
      and store.blockname_remove("temphandle") == 0)
# Reset the seeded sightings for the strike tests below: the pairing
# for 5555 already exists from the unit checks, which would make the
# group strike below look "already handled" only if 5555 were also
# gbanned — he is not, so the strike still fires. Fresh name instead:
store.blockname_add("zhangwei888_bot", OWNER, "scam network")
store.blockname_add("ylpay158", OWNER, "scam network")


async def main():
    # --- /blockname: multi-name paste + reason words + repeats. ------
    fb = FakeBot()
    cmd = FakeMsg(chat(GROUP), user(OWNER))
    await bot.on_blockname(upd(cmd, user(OWNER)), ctx(fb, [
        "@gAm0kiGk8bot", "@gbrcm9dfdbot", "@GIU3YH3Lbot", "payload", "bots"]))
    check("blockname: multi-name paste files every name",
          all(store.blockname_get(n) is not None
              for n in ("gam0kigk8bot", "gbrcm9dfdbot", "giu3yh3lbot")))
    check("blockname: words after the names become the reason",
          store.blockname_get("gam0kigk8bot")["reason"] == "payload bots")
    check("blockname: reply is the filed line",
          cmd.replies == ["🚫 Filed on the permanent blocklist: "
                          "@gAm0kiGk8bot, @gbrcm9dfdbot, @GIU3YH3Lbot — "
                          "banned on sight if they ever show up."])
    cmd = FakeMsg(chat(GROUP), user(OWNER))
    await bot.on_blockname(upd(cmd, user(OWNER)), ctx(fb, ["@ylpay158"]))
    check("blockname: re-filing an existing name says so",
          cmd.replies == ["Already on the blocklist: @ylpay158"])

    # --- /blockname refusals: owner + bot names can never be filed. --
    store.log_message(PROTECTED, OWNER, "The Owner (@OwnerHandle)", "hi", 1)
    store.log_message(PROTECTED, BOT_ID, "Lunc Assistant (@LuncAssistantBot)", "beep", 2)
    cmd = FakeMsg(chat(GROUP), user(OWNER))
    await bot.on_blockname(upd(cmd, user(OWNER)),
                           ctx(fb, ["@OwnerHandle", "@LuncAssistantBot"]))
    check("blockname: owner and bot names refused",
          cmd.replies == ["Refused (you / the bot — those names can "
                          "never be blocked): @OwnerHandle, @LuncAssistantBot"]
          and store.blockname_get("ownerhandle") is None
          and store.blockname_get("luncassistantbot") is None)
    cmd = FakeMsg(chat(GROUP), user(ELEV))
    await bot.on_blockname(upd(cmd, user(ELEV)), ctx(fb, ["@SomeScam"]))
    check("blockname: non-owner gets Owner only, nothing filed",
          cmd.replies == ["Owner only."]
          and store.blockname_get("somescam") is None)
    cmd = FakeMsg(chat(GROUP), user(OWNER))
    await bot.on_blockname(upd(cmd, user(OWNER)), ctx(fb, []))
    check("blockname: no names -> usage line",
          len(cmd.replies) == 1 and cmd.replies[0].startswith("Usage: /blockname"))

    # --- /unblockname round-trip. -------------------------------------
    cmd = FakeMsg(chat(GROUP), user(OWNER))
    await bot.on_unblockname(upd(cmd, user(OWNER)), ctx(fb, ["@GIU3YH3Lbot"]))
    check("unblockname: removal confirmed and effective",
          cmd.replies == ["✅ Removed from the permanent blocklist: @GIU3YH3Lbot"]
          and store.blockname_get("giu3yh3lbot") is None)
    cmd = FakeMsg(chat(GROUP), user(OWNER))
    await bot.on_unblockname(upd(cmd, user(OWNER)), ctx(fb, ["@GIU3YH3Lbot"]))
    check("unblockname: removing twice says it wasn't there",
          cmd.replies == ["Wasn't on the blocklist: @GIU3YH3Lbot"])
    store.blockname_add("giu3yh3lbot", OWNER, "payload bots")  # restore

    # --- /blocklist view: names + hit counts, owner only. -------------
    cmd = FakeMsg(chat(GROUP), user(OWNER))
    await bot.on_blocklist(upd(cmd, user(OWNER)), ctx(fb, []))
    view = cmd.replies[0] if cmd.replies else ""
    check("blocklist: view lists names with reasons and hit counts",
          view.startswith("*Permanent name blocklist (6)*")
          and "@ylzhangwei888 — scam network · 2 hit(s)" in view
          and "@ylpay158 — scam network · 0 hit(s)" in view)
    cmd = FakeMsg(chat(GROUP), user(ELEV))
    await bot.on_blocklist(upd(cmd, user(ELEV)), ctx(fb, []))
    check("blocklist: view is owner-only",
          cmd.replies == ["Owner only."])

    # --- Sighting in a group: full strike. ----------------------------
    fb = FakeBot()
    spammer = user(5555, "YLzhangwei888")
    m = FakeMsg(chat(GROUP), spammer, "buy usdt, we pay first", mid=42)
    await bot.on_observe_update(upd(m, spammer), ctx(fb))
    check("sighting(group): globally banned, recorded against the name",
          store.gban_get(5555) is not None
          and "name blocklist: @ylzhangwei888" in store.gban_get(5555)["reason"])
    check("sighting(group): AI-banned too", store.ai_ban_get(5555) is not None)
    check("sighting(group): id<->name pairing recorded",
          store.blockname_hit("ylzhangwei888", 5555) is False)
    check("sighting(group): banned in the sighting group AND protected groups",
          (GROUP, 5555) in fb.bans and (PROTECTED, 5555) in fb.bans)
    check("sighting(group): triggering message deleted",
          (GROUP, 42) in fb.deleted)
    check("sighting(group): mod_log has the blocklist-hit entry",
          any(r["action"] == "blocklist-hit" and r["target"] == 5555
              for r in store.mod_log_recent(10)))
    dms = owner_dms(fb)
    check("sighting(group): exactly one owner DM", len(dms) == 1)
    if dms:
        _cid, text, kwargs = dms[0]
        kb = kwargs.get("reply_markup")
        btn = kb.inline_keyboard[0][0] if kb else None
        check("sighting(group): DM text is exact",
              text == "🚫 Blocklist hit: @ylzhangwei888 (5555) just showed up "
                      "in Terra Luna Classic Chat — banned everywhere, permanently.")
        check("sighting(group): DM button is the report link",
              btn is not None and btn.text == "🚩 Report them"
              and btn.url == "https://t.me/YLzhangwei888")

    # --- Repeat sighting: already captured + banned -> quiet. ---------
    bans_before, dms_before = len(fb.bans), len(owner_dms(fb))
    m2 = FakeMsg(chat(GROUP), spammer, "again", mid=43)
    await bot.on_observe_update(upd(m2, spammer), ctx(fb))
    check("sighting(group): repeat sighting stays quiet",
          len(fb.bans) == bans_before and len(owner_dms(fb)) == dms_before
          and (GROUP, 43) not in fb.deleted)

    # --- Sighting in a DM: strike, no delete, no DM-chat ban. ---------
    fb = FakeBot()
    dm_user = user(6666, "zhangwei888_bot", is_bot=True)
    dm_chat = chat(6666, ctype="private", title=None)
    m = FakeMsg(dm_chat, dm_user, "hello", mid=7)
    await bot.on_observe_update(upd(m, dm_user), ctx(fb))
    check("sighting(DM): globally + AI banned",
          store.gban_get(6666) is not None and store.ai_ban_get(6666) is not None)
    check("sighting(DM): banned in protected groups, not in the DM chat",
          (PROTECTED, 6666) in fb.bans and (6666, 6666) not in fb.bans)
    check("sighting(DM): DM message NOT deleted", fb.deleted == [])
    dms = owner_dms(fb)
    check("sighting(DM): owner DM says it was a DM",
          len(dms) == 1
          and dms[0][1] == "🚫 Blocklist hit: @zhangwei888_bot (6666) just "
                           "showed up in a DM with the bot — banned "
                           "everywhere, permanently.")

    # --- Sighting via a button tap (callback query, no message). -----
    fb = FakeBot()
    tapper = user(8888, "ylpay158")
    u = types.SimpleNamespace(
        callback_query=types.SimpleNamespace(id="q1"), message=None,
        effective_message=None, effective_chat=chat(GROUP),
        effective_user=tapper, edited_message=None)
    await bot.on_observe_update(u, ctx(fb))
    check("sighting(button): tapper banned everywhere",
          store.gban_get(8888) is not None and (GROUP, 8888) in fb.bans
          and len(owner_dms(fb)) == 1)
    check("sighting(button): nothing deleted (no message of theirs)",
          fb.deleted == [])

    # --- Control: a normal member NAMING blocked accounts is safe. ----
    fb = FakeBot()
    member = user(7777, "regularmember")
    m = FakeMsg(chat(GROUP), member,
                "watch out for @ylzhangwei888 and @xxin7, total scammers",
                mid=50)
    await bot.on_observe_update(upd(m, member), ctx(fb))
    check("control: naming blocked accounts in text triggers nothing",
          store.gban_get(7777) is None and fb.bans == []
          and fb.deleted == [] and owner_dms(fb) == [])

    # --- Immunity: owner's name filed directly in the store. ----------
    store.blockname_add("ownerhandle", OWNER, "seeded directly")
    fb = FakeBot()
    m = FakeMsg(chat(GROUP), user(OWNER, "OwnerHandle"), "morning", mid=51)
    await bot.on_observe_update(upd(m, user(OWNER, "OwnerHandle")), ctx(fb))
    check("immunity: owner never struck, even with his name filed",
          store.gban_get(OWNER) is None and fb.bans == []
          and owner_dms(fb) == [])
    store.blockname_remove("ownerhandle")

    # --- List-ban filing: /gban with a never-seen name files it. ------
    fb = FakeBot()
    cmd = FakeMsg(chat(GROUP), user(OWNER))
    await bot.on_gban(upd(cmd, user(OWNER)), ctx(fb, ["@FreshScamHandle"]))
    check("list filing: not-found name lands on the blocklist",
          store.blockname_get("freshscamhandle") is not None
          and store.blockname_get("freshscamhandle")["added_by"] == OWNER)
    check("list filing: reply carries the filed line",
          cmd.replies == ["🚫 List ban done.\n"
                          "Not found: @FreshScamHandle — never seen by this "
                          "bot, can't ban by name; the auto-ban catches them "
                          "if they ever post.\n"
                          "Filed on the permanent blocklist: @FreshScamHandle "
                          "— banned on sight if they ever show up."])
    cmd = FakeMsg(chat(GROUP), user(OWNER))
    await bot.on_gban(upd(cmd, user(OWNER)), ctx(fb, ["@FreshScamHandle"]))
    check("list filing: second run files nothing new (no filed line)",
          len(cmd.replies) == 1
          and "Filed on the permanent blocklist" not in cmd.replies[0])


asyncio.run(main())
TOTAL = 38
print(f"\n{TOTAL - len(fails)}/{TOTAL} passed" if not fails
      else f"\nFAILED: {fails}")
sys.exit(1 if fails else 0)
