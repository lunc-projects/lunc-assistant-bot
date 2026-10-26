"""GitHub PR feature tests: /pr lookup, /pralerts + /prwatch group
settings, and the notification poller (mocked GitHub API).

The VM lacks the bot's Railway-only deps, so small telegram/httpx stubs
are installed before importing bot.py (same approach as test_games.py).
Run: python3 test_pr.py
"""
import asyncio
import os
import sys
import tempfile
import types
from urllib.parse import urlparse, parse_qs

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")

# --- Dependency stubs -------------------------------------------------
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
sys.modules["telegram.ext"] = ext

import store
import github_pr
import bot

fails = []


def check(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        fails.append(name)


REPO = "terra-classic-io/website"
INIT_TS = 1790000000  # before every "new" fixture timestamp below


def pr(num, **kw):
    d = {"number": num, "title": f"PR title {num}", "state": "open", "draft": False,
         "merged_at": None, "merged": False, "user": {"login": "author"},
         "body": f"Body of PR {num}", "html_url": f"https://github.com/{REPO}/pull/{num}",
         "created_at": "2026-10-20T10:00:00Z", "updated_at": "2026-10-20T10:00:00Z"}
    d.update(kw)
    return d


def comment(cid, num, login="alice", body="Nice work", kind="pull"):
    return {"id": cid, "user": {"login": login}, "body": body,
            "html_url": f"https://github.com/{REPO}/{kind}/{num}#issuecomment-{cid}",
            "created_at": "2026-10-21T10:00:00Z"}


class FakeGH:
    """Scriptable stand-in for github_pr.gh_get. Tests mutate the data
    between polls to simulate GitHub activity."""

    def __init__(self):
        self.pulls = []
        self.pr_detail = {}
        self.issue_comments = []
        self.review_comments = []
        self.reviews = {}
        self.fail = None

    @staticmethod
    def _slice(items, q):
        desc = (q.get("direction", ["asc"])[0] == "desc")
        out = sorted(items, key=lambda x: x["id"], reverse=desc)
        per = int(q.get("per_page", ["100"])[0])
        return [dict(x) for x in out[:per]]

    async def __call__(self, path):
        if self.fail is not None:
            raise self.fail
        u = urlparse(path)
        q = parse_qs(u.query)
        rest = u.path.strip("/").split("/")[3:]
        if rest == ["pulls"]:
            return [dict(x) for x in self.pulls]
        if rest == ["pulls", "comments"]:
            return self._slice(self.review_comments, q)
        if rest == ["issues", "comments"]:
            return self._slice(self.issue_comments, q)
        if len(rest) == 3 and rest[0] == "pulls" and rest[2] == "reviews":
            return [dict(r) for r in self.reviews.get(int(rest[1]), [])]
        if len(rest) == 2 and rest[0] == "pulls":
            n = int(rest[1])
            if n in self.pr_detail:
                return dict(self.pr_detail[n])
            raise github_pr.GhError(404)
        if len(rest) == 3 and rest[0] == "issues" and rest[2] == "comments":
            n = int(rest[1])
            mine = [c for c in self.issue_comments
                    if f"/pull/{n}#" in c["html_url"] or f"/issues/{n}#" in c["html_url"]]
            return self._slice(mine, q)
        raise AssertionError(f"unexpected GitHub path: {path}")


# --- parse_pr_args ------------------------------------------------------
check("parse: repo + number",
      github_pr.parse_pr_args(["terra-classic-io/website", "62"], []) == (REPO, 62, None))
check("parse: full URL",
      github_pr.parse_pr_args(["https://github.com/terra-classic-io/website/pull/62"], []) == (REPO, 62, None))
check("parse: bare number, one watched repo",
      github_pr.parse_pr_args(["62"], [REPO]) == (REPO, 62, None))
r = github_pr.parse_pr_args(["62"], [])
check("parse: bare number, no watched repo -> error", r[0] is None and "watching any repo" in r[2])
r = github_pr.parse_pr_args(["62"], [REPO, "classic-terra/core"])
check("parse: bare number, two watched repos -> error", r[0] is None and "more than one repo" in r[2])
r = github_pr.parse_pr_args([], [])
check("parse: no args -> usage", r[0] is None and r[2].startswith("Usage:"))
r = github_pr.parse_pr_args(["hello"], [])
check("parse: garbage -> usage error", r[0] is None and r[2].startswith("Usage:"))
r = github_pr.parse_pr_args([REPO, "abc"], [])
check("parse: non-numeric PR number -> error", r[0] is None and "isn't a PR number" in r[2])
check("valid_repo accepts owner/repo", github_pr.valid_repo("terra-classic-io/website"))
check("valid_repo rejects bare word", not github_pr.valid_repo("notarepo"))

# --- excerpt / formatting ------------------------------------------------
check("excerpt strips img tag + markdown image",
      github_pr.excerpt('Fix it <img width="10" src="x"> now ![a](b) please') == "Fix it now please")
check("excerpt collapses whitespace + truncates",
      github_pr.excerpt("a  \n b " + "x" * 400, 50).endswith("…")
      and "\n" not in github_pr.excerpt("a\n\nb"))

PR62 = pr(62, title="Improve readability of filtered ecosystem bubble map",
          user={"login": "someone"}, additions=120, deletions=45, changed_files=3,
          body='Issue I am trying to rectify on PR #60 remains. <img width="1290" src="https://example.com/x.png" />')
txt = github_pr.format_pr_detail(REPO, PR62, comment(900, 62, "LunaClassicDAO", "Looks good to me"))
check("detail: header", txt.splitlines()[0] == "🔀 PR #62 — terra-classic-io/website")
check("detail: title line", "Improve readability of filtered ecosystem bubble map" in txt)
check("detail: open state + author", "State: 🟢 Open · by someone" in txt)
check("detail: diff counts", "Files: 3 changed · +120 −45" in txt)
check("detail: body excerpt, img stripped", "Issue I am trying to rectify on PR #60 remains." in txt and "<img" not in txt)
check("detail: latest comment shown", "💬 Latest comment — LunaClassicDAO:" in txt and "> Looks good to me" in txt)
check("detail: link last", txt.splitlines()[-1] == f"https://github.com/{REPO}/pull/62")
check("label: draft", github_pr.pr_state_label(pr(1, draft=True)) == "📝 Open (draft)")
check("label: merged", github_pr.pr_state_label(pr(1, state="closed", merged_at="2026-10-25T00:00:00Z")) == "✅ Merged")
check("label: closed", github_pr.pr_state_label(pr(1, state="closed")) == "❌ Closed")

ev = {"kind": "comment", "repo": REPO, "number": 62,
      "title": "Improve readability of filtered ecosystem bubble map",
      "actor": "LunaClassicDAO", "url": f"https://github.com/{REPO}/pull/62#issuecomment-6405138657",
      "body": 'Issue I am trying to rectify on PR #60 remains by approving this PR. <img width="1290" height="995" src="https://github.com/user-attachments/assets/x" />'}
lines = github_pr.format_event(ev).splitlines()
check("event: Steve's example, first line", lines[0] == "💬 LunaClassicDAO commented on PR #62 — terra-classic-io/website")
check("event: title second", lines[1] == "Improve readability of filtered ecosystem bubble map")
check("event: quoted excerpt, img stripped", lines[2].startswith("> Issue I am trying to rectify") and "<img" not in lines[2])
check("event: url last", lines[-1] == ev["url"])
check("event emoji: opened", github_pr.format_event({"kind": "opened", "repo": REPO, "number": 1, "title": "t", "actor": "a", "url": "u"}).startswith("🆕 a opened PR #1"))
check("event emoji: merged", github_pr.format_event({"kind": "merged", "repo": REPO, "number": 1, "title": "t", "actor": "a", "url": "u"}).startswith("✅ PR #1 merged"))
check("event emoji: closed", github_pr.format_event({"kind": "closed", "repo": REPO, "number": 1, "title": "t", "actor": "a", "url": "u"}).startswith("❌ PR #1 closed"))
check("event emoji: review w/ state", "👀 bob reviewed PR #1" in github_pr.format_event(
    {"kind": "review", "repo": REPO, "number": 1, "title": "t", "actor": "bob", "review_state": "APPROVED", "url": "u"}))

# --- store: settings, subscriptions, state -------------------------------
G1, G2 = -1001, -2002
check("pr alerts default OFF", not store.pr_alerts_enabled(G1))
store.set_pr_alerts(G1, True)
check("pr alerts ON after set", store.pr_alerts_enabled(G1))
check("chats_with_pr_on lists the group", store.chats_with_pr_on() == [G1])
store.set_pr_alerts(G1, False)
check("pr alerts OFF after unset", not store.pr_alerts_enabled(G1))

store.pr_watch_add(G1, REPO, thread_id=555)
rows = store.pr_watch_list(G1)
check("watch add stores repo + thread", len(rows) == 1 and rows[0]["repo"] == REPO and rows[0]["thread_id"] == 555)
store.pr_watch_add(G1, REPO)  # no thread -> keeps the stored one
check("watch re-add without thread keeps thread", store.pr_watch_list(G1)[0]["thread_id"] == 555)
store.pr_watch_add(G1, REPO, thread_id=777)
check("watch re-add with thread updates it", store.pr_watch_list(G1)[0]["thread_id"] == 777)
store.pr_watch_add(G1, "classic-terra/core")
check("watch list sorted, two repos", [r["repo"] for r in store.pr_watch_list(G1)] == ["classic-terra/core", REPO])
check("watch remove returns 1", store.pr_watch_remove(G1, "classic-terra/core") == 1)
check("watch remove again returns 0", store.pr_watch_remove(G1, "classic-terra/core") == 0)

store.pr_watch_add(G2, REPO)  # watched but alerts OFF
check("active subs exclude alerts-off chats", [s["chat_id"] for s in store.pr_active_subscriptions()] == [])
store.set_pr_alerts(G2, True)
check("active subs include alerts-on chats", [s["chat_id"] for s in store.pr_active_subscriptions()] == [G2])
store.set_pr_alerts(G2, False)

STATE_REPO = "some-org/state-repo"  # isolated: REPO's state must stay pristine for the job test
check("repo state starts empty", store.pr_get_state(STATE_REPO) is None)
store.pr_set_state(STATE_REPO, {"init_ts": 1, "last_comment_id": 5, "prs": {}})
check("repo state roundtrip", store.pr_get_state(STATE_REPO)["last_comment_id"] == 5)
store.pr_set_state(STATE_REPO, {"init_ts": 2, "last_comment_id": 9, "prs": {}})
check("repo state upsert", store.pr_get_state(STATE_REPO)["init_ts"] == 2)

# --- poller: diff via poll_repo with a fake GitHub -------------------------
fake = FakeGH()
fake.pulls = [pr(62), pr(12, draft=True, created_at="2025-06-01T00:00:00Z")]
fake.issue_comments = [comment(100, 62)]


async def poll(state, **kw):
    return await github_pr.poll_repo(REPO, state, fetch=fake, **kw)


async def poller_case():
    events, st = await poll(None, now_ts=INIT_TS)
    check("poller: first watch initializes, no events", events == [])
    check("poller: init snapshot has both PRs", set(st["prs"]) == {"62", "12"})
    check("poller: init cursor at latest comment", st["last_comment_id"] == 100)

    events, st = await poll(st, now_ts=INIT_TS)
    check("poller: re-poll same data -> zero events", events == [])

    fake.issue_comments.append(comment(101, 62, "LunaClassicDAO",
                                       'Rectified on PR #60. <img src="https://x/y.png">'))
    events, st = await poll(st, now_ts=INIT_TS)
    check("poller: one new comment -> exactly one event", len(events) == 1 and events[0]["kind"] == "comment")
    check("poller: comment event fields", events[0]["actor"] == "LunaClassicDAO" and events[0]["number"] == 62)
    msg = github_pr.format_event(events[0])
    check("poller: comment formats like the example",
          msg.splitlines()[0] == "💬 LunaClassicDAO commented on PR #62 — terra-classic-io/website"
          and "PR title 62" in msg)
    events, st = await poll(st, now_ts=INIT_TS)
    check("poller: same comment never re-posts", events == [])

    fake.issue_comments.append(comment(102, 9, "alice", "on a plain issue", kind="issues"))
    events, st = await poll(st, now_ts=INIT_TS)
    check("poller: plain-issue comments are not PR events", events == [] and st["last_comment_id"] == 102)

    fake.pulls.insert(0, pr(63, created_at="2026-10-24T09:00:00Z", updated_at="2026-10-24T09:00:00Z"))
    events, st = await poll(st, now_ts=INIT_TS)
    check("poller: PR opened after watch -> 🆕 event", len(events) == 1 and events[0]["kind"] == "opened")

    fake.pulls.insert(0, pr(64, created_at="2025-03-01T00:00:00Z"))
    events, st = await poll(st, now_ts=INIT_TS)
    check("poller: pre-watch PR entering the page is not news", events == [])

    fake.pulls = [pr(63, created_at="2026-10-24T09:00:00Z", updated_at="2026-10-25T09:00:00Z")] + [p for p in fake.pulls if p["number"] != 63]
    fake.reviews[63] = [{"id": 500, "user": {"login": "bob"}, "state": "APPROVED",
                         "body": "LGTM", "html_url": f"https://github.com/{REPO}/pull/63#pullrequestreview-500",
                         "submitted_at": "2026-10-25T09:00:00Z"}]
    events, st = await poll(st, now_ts=INIT_TS)
    check("poller: submitted review -> 👀 event", len(events) == 1 and events[0]["kind"] == "review"
          and events[0]["review_state"] == "APPROVED")

    fake.pulls = [pr(63, created_at="2026-10-24T09:00:00Z", updated_at="2026-10-25T10:00:00Z")] + [p for p in fake.pulls if p["number"] != 63]
    fake.reviews[63].append({"id": 501, "user": {"login": "bob"}, "state": "COMMENTED",
                              "body": "", "html_url": f"https://github.com/{REPO}/pull/63#pullrequestreview-501",
                              "submitted_at": "2026-10-25T10:00:00Z"})
    events, st = await poll(st, now_ts=INIT_TS)
    check("poller: empty COMMENTED review shell is silent", events == [])
    check("poller: review cursor still advances", st["prs"]["63"]["reviews_last_id"] == 501)

    fake.pulls = [pr(62, state="closed", merged_at="2026-10-25T11:00:00Z",
                     updated_at="2026-10-25T11:00:00Z")] + [p for p in fake.pulls if p["number"] != 62]
    events, st = await poll(st, now_ts=INIT_TS)
    check("poller: merge -> ✅ event, once", len(events) == 1 and events[0]["kind"] == "merged")
    events, st = await poll(st, now_ts=INIT_TS)
    check("poller: merge does not re-post", events == [])

    fake.pulls = [pr(12, draft=False, created_at="2025-06-01T00:00:00Z",
                     updated_at="2026-10-25T12:00:00Z")] + [p for p in fake.pulls if p["number"] != 12]
    events, st = await poll(st, now_ts=INIT_TS)
    check("poller: draft -> ready for review event", len(events) == 1 and events[0]["kind"] == "ready")

    fake.issue_comments.append(comment(103, 62, "prbot", "automated note"))
    events, st = await poll(st, now_ts=INIT_TS, skip_logins=("prbot",))
    check("poller: bot's own events are skipped", events == [] and st["last_comment_id"] == 103)

    fake.issue_comments.append({"id": 104, "user": {"login": "carol"}, "body": "inline thought",
                                 "html_url": f"https://github.com/{REPO}/pull/63#discussion_r104",
                                 "created_at": "2026-10-25T13:00:00Z"})
    fake.review_comments.append({"id": 104, "user": {"login": "carol"}, "body": "inline thought",
                                  "html_url": f"https://github.com/{REPO}/pull/63#discussion_r104",
                                  "pull_request_url": f"https://api.github.com/repos/{REPO}/pulls/63",
                                  "created_at": "2026-10-25T13:00:00Z"})
    fake.issue_comments.pop()  # the same comment is NOT an issue comment; keep feeds honest
    events, st = await poll(st, now_ts=INIT_TS)
    check("poller: inline review comment -> 💬 event", len(events) == 1 and events[0]["kind"] == "comment"
          and events[0]["number"] == 63)


asyncio.run(poller_case())

# --- handlers ---------------------------------------------------------------
class FakeBot:
    def __init__(self, member_status="administrator"):
        self.member_status = member_status
        self.sent = []

    async def get_chat_member(self, chat_id, user_id):
        return types.SimpleNamespace(status=self.member_status)

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append((chat_id, text, kwargs))


class FakeMessage:
    def __init__(self, thread_id=None):
        self.replies = []
        self.message_thread_id = thread_id

    async def reply_text(self, text, **kwargs):
        self.replies.append(text)


def make_update(chat_id, user_id=42, thread_id=None, chat_type="supergroup"):
    return types.SimpleNamespace(
        effective_chat=types.SimpleNamespace(id=chat_id, type=chat_type),
        effective_user=types.SimpleNamespace(id=user_id),
        message=FakeMessage(thread_id))


def ctx(args, fake_bot):
    return types.SimpleNamespace(args=args, bot=fake_bot)


async def handler_case():
    chat = -3003
    member_bot = FakeBot("member")
    upd = make_update(chat)
    await bot.on_pralerts(upd, ctx(["on"], member_bot))
    check("handler: non-admin cannot turn alerts on", not store.pr_alerts_enabled(chat)
          and "Only group admins" in upd.message.replies[0])
    await bot.on_prwatch(upd, ctx(["add", REPO], member_bot))
    check("handler: non-admin cannot add a watch", store.pr_watch_list(chat) == []
          and "Only group admins" in upd.message.replies[-1])

    admin_bot = FakeBot("administrator")
    upd = make_update(chat, thread_id=555)
    await bot.on_pralerts(upd, ctx(["on"], admin_bot))
    check("handler: admin turns alerts on", store.pr_alerts_enabled(chat))
    rows = store.pr_watch_list(chat)
    check("handler: defaults added on first enable",
          [r["repo"] for r in rows] == sorted(github_pr.DEFAULT_REPOS))
    check("handler: defaults carry the command's topic", all(r["thread_id"] == 555 for r in rows))
    check("handler: enable reply names the defaults", "terra-classic-io/website" in upd.message.replies[0])

    upd = make_update(chat)
    await bot.on_pralerts(upd, ctx([], admin_bot))
    check("handler: bare /pralerts shows status", "GitHub PR notifications: ON" in upd.message.replies[0])

    upd = make_update(chat)
    await bot.on_prwatch(upd, ctx(["add", "notarepo"], admin_bot))
    check("handler: invalid repo rejected", "Usage: /prwatch add" in upd.message.replies[0]
          and len(store.pr_watch_list(chat)) == 2)
    upd = make_update(chat)
    await bot.on_prwatch(upd, ctx(["add", "some-org/some-repo"], admin_bot))
    check("handler: admin adds a repo", "some-org/some-repo" in [r["repo"] for r in store.pr_watch_list(chat)])
    upd = make_update(chat)
    await bot.on_prwatch(upd, ctx(["remove", "some-org/some-repo"], admin_bot))
    check("handler: admin removes a repo", "Stopped watching" in upd.message.replies[0])
    upd = make_update(chat)
    await bot.on_prwatch(upd, ctx(["remove", "some-org/some-repo"], admin_bot))
    check("handler: removing twice says so", "isn't on this chat's watch list" in upd.message.replies[0])
    upd = make_update(chat)
    await bot.on_prwatch(upd, ctx([], admin_bot))
    check("handler: bare /prwatch lists repos", "terra-classic-io/website" in upd.message.replies[0])

    upd = make_update(chat)
    await bot.on_pralerts(upd, ctx(["off"], admin_bot))
    check("handler: admin turns alerts off", not store.pr_alerts_enabled(chat))

    # owner bypass: not a group admin, still allowed
    old_owner = bot.OWNER_ID
    bot.OWNER_ID = 999
    try:
        upd = make_update(chat, user_id=999)
        await bot.on_pralerts(upd, ctx(["on"], member_bot))
        check("handler: bot owner can change settings anywhere", store.pr_alerts_enabled(chat))
    finally:
        bot.OWNER_ID = old_owner
        store.set_pr_alerts(chat, False)


asyncio.run(handler_case())


async def pr_lookup_case():
    chat = -4004
    detail = pr(62, title="Improve readability of filtered ecosystem bubble map",
                additions=120, deletions=45, changed_files=3)

    async def fake_detail(repo, number, fetch=None):
        return detail, comment(900, 62, "LunaClassicDAO", "Looks good")

    orig = github_pr.fetch_pr_detail
    github_pr.fetch_pr_detail = fake_detail
    try:
        upd = make_update(chat)
        await bot.on_pr(upd, ctx([REPO, "62"], FakeBot()))
        check("/pr: repo+number replies with the PR", "PR #62" in upd.message.replies[0]
              and "Improve readability" in upd.message.replies[0])
        upd = make_update(chat)
        await bot.on_pr(upd, ctx([f"https://github.com/{REPO}/pull/62"], FakeBot()))
        check("/pr: URL form works", "PR #62" in upd.message.replies[0])
        store.pr_watch_add(chat, REPO)
        upd = make_update(chat)
        await bot.on_pr(upd, ctx(["62"], FakeBot()))
        check("/pr: bare number uses the one watched repo", "PR #62" in upd.message.replies[0])
        upd = make_update(chat)
        await bot.on_pr(upd, ctx([], FakeBot()))
        check("/pr: no args -> usage", upd.message.replies[0].startswith("Usage:"))
    finally:
        github_pr.fetch_pr_detail = orig

    async def missing(repo, number, fetch=None):
        raise github_pr.GhError(404)

    github_pr.fetch_pr_detail = missing
    try:
        upd = make_update(chat)
        await bot.on_pr(upd, ctx([REPO, "62"], FakeBot()))
        check("/pr: 404 -> plain couldn't-find, no crash", "Couldn't find PR #62" in upd.message.replies[0])
    finally:
        github_pr.fetch_pr_detail = orig

    async def limited(repo, number, fetch=None):
        raise github_pr.GhError(403)

    github_pr.fetch_pr_detail = limited
    try:
        upd = make_update(chat)
        await bot.on_pr(upd, ctx([REPO, "62"], FakeBot()))
        check("/pr: rate limit -> plain message", "rate-limiting" in upd.message.replies[0])
    finally:
        github_pr.fetch_pr_detail = orig


asyncio.run(pr_lookup_case())

# --- the poller job, end to end ----------------------------------------------
async def job_case():
    chat = -5005
    store.set_pr_alerts(chat, True)
    store.pr_watch_add(chat, REPO, thread_id=777)
    jfake = FakeGH()
    jfake.pulls = [pr(62)]
    jfake.issue_comments = [comment(100, 62)]
    orig_get, orig_gap = github_pr.gh_get, bot.PR_SEND_GAP
    github_pr.gh_get = jfake
    bot.PR_SEND_GAP = 0
    try:
        fb = FakeBot()
        await bot.job_pr_check(types.SimpleNamespace(bot=fb))
        check("job: first run initializes silently", fb.sent == [])
        jfake.issue_comments.append(comment(101, 62, "LunaClassicDAO", "Ship it"))
        await bot.job_pr_check(types.SimpleNamespace(bot=fb))
        check("job: one new comment -> one post", len(fb.sent) == 1)
        if fb.sent:
            cid, text, kw = fb.sent[0]
            check("job: post lands in the subscription's topic", cid == chat and kw.get("message_thread_id") == 777)
            check("job: post text matches the example shape",
                  text.splitlines()[0] == "💬 LunaClassicDAO commented on PR #62 — terra-classic-io/website")
        await bot.job_pr_check(types.SimpleNamespace(bot=fb))
        check("job: re-poll with same data posts nothing", len(fb.sent) == 1)
        check("job: cursors persisted in SQLite", store.pr_get_state(REPO)["last_comment_id"] == 101)

        jfake.fail = github_pr.GhError(403)
        await bot.job_pr_check(types.SimpleNamespace(bot=fb))
        check("job: rate limit backs off quietly, no crash, no posts", len(fb.sent) == 1)
        jfake.fail = None
    finally:
        github_pr.gh_get = orig_get
        bot.PR_SEND_GAP = orig_gap
        store.set_pr_alerts(chat, False)


asyncio.run(job_case())

print()
print("FAILURES:", fails if fails else "none")
sys.exit(1 if fails else 0)
