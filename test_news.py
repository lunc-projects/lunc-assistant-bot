# /news live-headline tests (owner request 2026-10-29): /news serves REAL
# headlines from CoinDesk + Cointelegraph RSS (bounded fetch, ~5 min
# cache, newest ~8, source + relative time + link). When every feed
# fails the answer is a plain "news feed unreachable right now" — never
# invented headlines. Output passes through strip_mentions like the
# summary family. And /ask carries the current-events honesty rule on
# both ask paths: the AI has no live news wire of its own, questions
# needing today's facts get a SHORT answer pointing at /news — no
# "check their Twitter/blog/Reddit" waffle, no speculation.
#
# Run: python3 test_news.py
import asyncio
import inspect
import os
import sys
import tempfile
import types

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["OWNER_TELEGRAM_ID"] = "999"

# --- Dependency stubs (same pattern as test_ai_policy.py) ---
# httpx is force-stubbed (not setdefault): these tests exercise the
# news fetcher's merge/failure logic with a fake client, so the stub
# must win even where a real httpx happens to be installed.
fake_httpx = types.ModuleType("httpx")


class _FakeAsyncClient:
    def __init__(self, *args, **kwargs):
        self.args, self.kwargs = args, kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, headers=None):  # pragma: no cover - patched per test
        raise RuntimeError("tests must patch news._fetch_one")


fake_httpx.AsyncClient = _FakeAsyncClient
sys.modules["httpx"] = fake_httpx

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

import ai_client
import news
import bot

passed = 0
failed = 0


def check(cond, msg):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ok: {msg}")
    else:
        failed += 1
        print(f"  FAIL: {msg}")


# A fixed "now": Thu, 29 Oct 2026 18:00:00 UTC
NOW = 1793296800.0

FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<title>Fixture Feed</title>
<item><title><![CDATA[Bitcoin &amp; Ethereum rally as   ETF
inflows climb]]></title><link>https://example.com/story-1</link>
<pubDate>Thu, 29 Oct 2026 17:30:00 +0000</pubDate></item>
<item><title>Second story</title><link>https://example.com/story-2</link>
<pubDate>Thu, 29 Oct 2026 16:00:00 +0000</pubDate></item>
<item><title>No link item — must be skipped</title>
<pubDate>Thu, 29 Oct 2026 17:45:00 +0000</pubDate></item>
</channel></rss>"""

print("== RSS parse (fixture) ==")
items = news.parse_feed(FIXTURE, "CoinDesk")
check(len(items) == 2, "fixture parses to 2 items (linkless item skipped)")
check(items[0]["title"] == "Bitcoin & Ethereum rally as ETF inflows climb",
      "CDATA + entity decoded, whitespace collapsed")
check(items[0]["link"] == "https://example.com/story-1", "link parsed")
check(items[0]["source"] == "CoinDesk", "source stamped")
check(abs(items[0]["ts"] - 1793295000.0) < 1, "pubDate parsed to epoch (17:30 UTC)")
check(news.parse_feed("this is not xml <<<", "CoinDesk") == [],
      "malformed XML parses to [] (no crash)")

print("== relative time ==")
check(news.rel_time(NOW - 30, NOW) == "just now", "30s -> just now")
check(news.rel_time(NOW - 24 * 60, NOW) == "24m ago", "24m -> '24m ago'")
check(news.rel_time(NOW - 3 * 3600, NOW) == "3h ago", "3h -> '3h ago'")
check(news.rel_time(NOW - 2 * 86400, NOW) == "2d ago", "2d -> '2d ago'")
check(news.rel_time(0, NOW) == "", "no date -> no age shown")

print("== formatting ==")
sample = [
    {"title": "Alpha headline", "link": "https://a.example/1", "ts": NOW - 600, "source": "CoinDesk"},
    {"title": "Beta headline", "link": "https://b.example/2", "ts": NOW - 7200, "source": "Cointelegraph"},
]
text = news.format_headlines(sample, now=NOW)
check(text.startswith("📰 Crypto headlines — live"), "header present")
check("• Alpha headline\n  CoinDesk · 10m ago\n  https://a.example/1" in text,
      "item shape: title / source · age / link")
check("Cointelegraph · 2h ago" in text, "second source + age present")
many = [{"title": f"H{i}", "link": f"https://x.example/{i}", "ts": NOW - i * 60,
         "source": "CoinDesk"} for i in range(10)]
check(news.format_headlines(many, now=NOW).count("\n• ") == news.MAX_HEADLINES == 8,
      "output capped at 8 headlines")
check("No headlines came back" in news.format_headlines([], now=NOW),
      "empty feed result is stated plainly")

print("== cache behaviour ==")
news._reset_cache()
calls = {"n": 0}


async def counting_fetcher():
    calls["n"] += 1
    return sample


first = asyncio.run(news.get_headlines(now=NOW, fetcher=counting_fetcher))
second = asyncio.run(news.get_headlines(now=NOW + 60, fetcher=counting_fetcher))
check(first == sample and second == sample and calls["n"] == 1,
      "second call inside the TTL is served from cache (fetcher ran once)")
third = asyncio.run(news.get_headlines(now=NOW + news.CACHE_TTL + 1, fetcher=counting_fetcher))
check(third == sample and calls["n"] == 2, "call after the TTL refetches")
check(news.CACHE_TTL == 300, "cache TTL is ~5 minutes")

print("== failure path honesty ==")
news._reset_cache()
fail_calls = {"n": 0}


async def dead_fetcher():
    fail_calls["n"] += 1
    return None


check(asyncio.run(news.get_headlines(now=NOW, fetcher=dead_fetcher)) is None,
      "total failure returns None (no invented headlines)")
out = asyncio.run(news.news_text(now=NOW, fetcher=dead_fetcher))
check(out == news.UNREACHABLE_TEXT and "News feed unreachable right now" in out,
      "both feeds down -> the plain unreachable message")
check(fail_calls["n"] == 2, "failures are not cached — /news retries next time")

print("== merge: one feed down still serves, sorted newest-first ==")
news._reset_cache()
real_fetch_one = news._fetch_one


async def flaky(client, source, url):
    if source == "Cointelegraph":
        raise RuntimeError("feed down")
    return [{"title": "Old CD", "link": "https://cd/old", "ts": NOW - 5000, "source": "CoinDesk"},
            {"title": "New CD", "link": "https://cd/new", "ts": NOW - 100, "source": "CoinDesk"}]


news._fetch_one = flaky
try:
    merged = asyncio.run(news._fetch_all())
finally:
    news._fetch_one = real_fetch_one
check(merged is not None and [m["title"] for m in merged] == ["New CD", "Old CD"],
      "surviving feed serves, merged list sorted newest-first")


async def all_dead(client, source, url):
    raise RuntimeError("down")


news._fetch_one = all_dead
try:
    check(asyncio.run(news._fetch_all()) is None, "every feed raising -> None")
finally:
    news._fetch_one = real_fetch_one
news._reset_cache()

print("== fetch wiring ==")
check([u for _, u in news.FEEDS] == ["https://www.coindesk.com/arc/outboundfeeds/rss/",
                                     "https://cointelegraph.com/rss"],
      "feeds are CoinDesk + Cointelegraph RSS")
check(0 < news.FETCH_TIMEOUT <= 30, "fetch timeout is bounded")

print("== /news handler: strip_mentions applies ==")


class _FakeMsg:
    def __init__(self):
        self.sent = []

    async def reply_text(self, text, **kwargs):
        self.sent.append(text)


fake_update = types.SimpleNamespace(effective_message=_FakeMsg())
news._cache["items"] = [{"title": "Big move by @somehandle today",
                          "link": "https://x.example/1", "ts": NOW - 60,
                          "source": "CoinDesk"}]
news._cache["fetched_at"] = NOW
import time as _time
# on_news uses the real clock via news_text(); seed the cache against it.
news._cache["fetched_at"] = _time.time()
asyncio.run(bot.on_news(fake_update, None))
sent = fake_update.effective_message.sent[0]
check("@somehandle" not in sent and "somehandle" in sent,
      "handler output strips @mentions (no re-tagging from a headline)")
check("📰 Crypto headlines — live" in sent, "handler serves the headline list")
news._reset_cache()

print("== command registration / lists ==")
bot_src = inspect.getsource(bot)
check('CommandHandler("news", on_news)' in bot_src, "/news command registered")
check("/news — latest crypto headlines" in bot.HELP, "/news listed in /help")
check('("news","Latest crypto headlines")' in bot_src, "/news in the Telegram command list")
menu_datas = [b.callback_data for row in bot.MENU_KB.inline_keyboard for b in row]
check("menu:news" in menu_datas, "/news has a /menu button")

print("== /ask current-events honesty rule ==")
rule = ai_client.CURRENT_EVENTS_RULE
check("NO live news wire" in rule, "rule states the AI has no live news wire")
check("/news" in rule, "rule points to /news for headlines")
check("NEVER speculate" in rule, "rule forbids speculating about ongoing events")
check("Twitter" in rule and "Reddit" in rule,
      "rule bans the generic check-Twitter/blog/Reddit waffle")
check("answer SHORT" in rule, "rule requires a short answer")
check(bot_src.count("CURRENT_EVENTS_RULE") >= 2,
      "rule is appended on BOTH ask paths (/ask + @mention)")
check("CURRENT_EVENTS_RULE" not in ai_client.AI_RULES and "CURRENT_EVENTS_RULE" not in ai_client.SUMMARY_SYSTEM,
      "summaries/tldr prompts untouched by the rule")

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
