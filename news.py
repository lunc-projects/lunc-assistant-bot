"""Live crypto news headlines — public RSS only (owner request 2026-10-29).

The bot's chain data is live but /ask has no current-events source, so an
"is Binance down?" question got a generic brush-off. /news is the honest
fix: real headlines fetched from two public RSS feeds at ask time.

Rules baked in here:
- Headlines are ONLY what the feeds return — never invented, never padded.
- Both feeds are fetched with a bounded timeout; one feed down still
  serves the other's headlines. Both down -> None, and the caller says
  "news feed unreachable right now" plainly.
- Results are cached ~5 minutes so a busy group can't hammer the feeds.
- Output is plain text (headlines are outside content — no Markdown
  parsing, so a stray * or _ in a title can't break the message). The
  /news handler passes the text through ai_client.strip_mentions like
  the summary family, so no headline can re-tag a group member.
"""
import asyncio, html, os, re, time
import xml.etree.ElementTree as ET
from datetime import timezone
from email.utils import parsedate_to_datetime

import httpx

FEEDS = [
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("Cointelegraph", "https://cointelegraph.com/rss"),
]
FETCH_TIMEOUT = 12          # seconds, per feed — bounded like the rest of the bot
CACHE_TTL = 300             # ~5 minutes
MAX_HEADLINES = 8
_TITLE_CAP = 160

UNREACHABLE_TEXT = ("📰 News feed unreachable right now — both headline "
                    "sources (CoinDesk + Cointelegraph) failed to answer. "
                    "Try again in a bit.")

_cache = {"fetched_at": 0.0, "items": []}


def _clean_title(raw):
    """One-line, entity-decoded, whitespace-collapsed headline."""
    t = html.unescape(raw or "")
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) > _TITLE_CAP:
        t = t[:_TITLE_CAP - 1].rstrip() + "…"
    return t


def _parse_date(item):
    """pubDate (RFC 822) -> epoch seconds; dc:date (ISO) as fallback."""
    raw = item.findtext("pubDate")
    if raw:
        try:
            dt = parsedate_to_datetime(raw.strip())
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except Exception:
            pass
    raw = item.findtext("{http://purl.org/dc/elements/1.1/}date")
    if raw:
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except Exception:
            pass
    return 0.0


def parse_feed(xml_text, source):
    """Parse one RSS 2.0 document into headline dicts (pure function —
    unit-testable with a fixture). Returns [] on malformed XML; callers
    treat a raise-free empty parse of one feed separately from a fetch
    failure of both."""
    try:
        root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    except Exception:
        return []
    items = []
    for item in root.iter("item"):
        title = _clean_title(item.findtext("title"))
        link = (item.findtext("link") or "").strip()
        if not title or not link:
            continue
        items.append({"title": title, "link": link,
                      "ts": _parse_date(item), "source": source})
    return items


def rel_time(ts, now):
    """Short relative age: 'just now', '24m ago', '3h ago', '2d ago'.
    Empty string when the feed gave no usable date."""
    if not ts:
        return ""
    secs = max(0, int(now - ts))
    if secs < 90:
        return "just now"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    return f"{secs // 86400}d ago"


def format_headlines(items, now=None):
    """Plain-text /news body: newest first, source + age + link per item."""
    now = time.time() if now is None else now
    if not items:
        return ("📰 No headlines came back from the feeds just now "
                "(CoinDesk + Cointelegraph). Try again in a bit.")
    lines = ["📰 Crypto headlines — live"]
    for it in items[:MAX_HEADLINES]:
        age = rel_time(it["ts"], now)
        meta = it["source"] + (f" · {age}" if age else "")
        lines.append(f"\n• {it['title']}\n  {meta}\n  {it['link']}")
    lines.append("\nHeadlines via CoinDesk + Cointelegraph RSS — tap a link "
                 "for the full story. /ask has no live news wire of its own; "
                 "this is where the latest headlines live.")
    return "\n".join(lines)


async def _fetch_one(client, source, url):
    r = await client.get(url, headers={"User-Agent": "LUNC-Assistant-Bot/1.0 (+news RSS reader)"})
    r.raise_for_status()
    items = parse_feed(r.text, source)
    if not items:
        raise ValueError(f"{source}: feed answered but parsed to zero headlines")
    return items


async def _fetch_all():
    """Fetch every feed concurrently. Returns the merged, newest-first
    headline list, or None when EVERY feed failed (fetch error or zero
    parsed headlines) — the honest 'unreachable' signal."""
    async with httpx.AsyncClient(timeout=FETCH_TIMEOUT, follow_redirects=True,
                                 proxy=os.getenv('OUTBOUND_PROXY') or None) as c:
        results = await asyncio.gather(
            *[_fetch_one(c, source, url) for source, url in FEEDS],
            return_exceptions=True)
    merged, ok = [], 0
    for res in results:
        if isinstance(res, Exception):
            print(f"news fetch: {res}")
            continue
        ok += 1
        merged += res
    if not ok:
        return None
    merged.sort(key=lambda it: it["ts"], reverse=True)
    return merged[:MAX_HEADLINES]


async def get_headlines(now=None, fetcher=None):
    """Cached headline list. Within CACHE_TTL of the last successful
    fetch the cache answers (no network). On a total fetch failure
    returns None and the failure is NOT cached, so the next /news
    retries. `fetcher` is injectable for tests."""
    now = time.time() if now is None else now
    if _cache["items"] and now - _cache["fetched_at"] < CACHE_TTL:
        return _cache["items"]
    items = await (fetcher() if fetcher is not None else _fetch_all())
    if items is None:
        return None
    _cache["items"] = items
    _cache["fetched_at"] = now
    return items


async def news_text(now=None, fetcher=None):
    """Final /news reply body (before strip_mentions at the handler)."""
    items = await get_headlines(now=now, fetcher=fetcher)
    if items is None:
        return UNREACHABLE_TEXT
    return format_headlines(items, now=now)


def _reset_cache():
    """Test helper — no production caller."""
    _cache["items"] = []
    _cache["fetched_at"] = 0.0
