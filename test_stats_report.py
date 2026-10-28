"""Cross-bot stats tests (owner ruling 2026-10-27): this bot publishes
its counts to a shared Upstash DB and reads the other three bots'
counts back for the ONE combined daily report.

Covers: publish payload shape + 3-day TTL, no-op when UPSTASH_STATS_*
is unset, failure swallowing, read_bot (fresh payload / missing key /
transport failure raises so the caller can fall back), freshness
window, and current_counts() shape from the usage registry.

Run: python3 test_stats_report.py"""
import asyncio
import json
import os
import sys
import tempfile
import time
import types

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["OWNER_TELEGRAM_ID"] = "999"

# httpx is a Railway-only dep on this VM; stub it — every call below
# injects a fake client factory, so no real HTTP ever happens.
_httpx = types.ModuleType("httpx")


class _NoRealHTTP:
    def __init__(self, *a, **k):
        raise AssertionError("real HTTP not allowed in tests")


_httpx.AsyncClient = _NoRealHTTP
sys.modules.setdefault("httpx", _httpx)

import stats_report
import store

fails = []


def check(label, cond):
    print(("  ok: " if cond else "  FAIL: ") + label)
    if not cond:
        fails.append(label)


class FakeResp:
    def __init__(self, data=None, status=200):
        self._data = data if data is not None else {"result": "OK"}
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._data


class FakeClient:
    def __init__(self, recorder=None, get_result=None, fail=False):
        self.recorder = recorder if recorder is not None else []
        self.get_result = get_result
        self.fail = fail

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, content=None):
        self.recorder.append(("POST", url, headers, content))
        if self.fail:
            raise RuntimeError("network down")
        return FakeResp()

    async def get(self, url, headers=None):
        self.recorder.append(("GET", url, headers, None))
        if self.fail:
            raise RuntimeError("network down")
        return FakeResp({"result": self.get_result})


print("== no-op when unconfigured ==")
os.environ.pop("UPSTASH_STATS_URL", None)
os.environ.pop("UPSTASH_STATS_TOKEN", None)
check("unconfigured without env", stats_report.configured() is False)
check("publish is a silent no-op when unset",
      asyncio.run(stats_report.publish({"people_total": 1})) is False)
check("read_bot returns None when unset",
      asyncio.run(stats_report.read_bot("garuda")) is None)

print("== publish writes the payload with a 3-day TTL ==")
os.environ["UPSTASH_STATS_URL"] = "https://stats.example.test/"
os.environ["UPSTASH_STATS_TOKEN"] = "tok123"
calls = []
ok = asyncio.run(stats_report.publish(
    {"people_total": 5, "groups_member": 2},
    client_factory=lambda: FakeClient(calls)))
check("publish reports success", ok is True)
check("exactly one HTTP call", len(calls) == 1)
_kind, url, headers, content = calls[0]
check("SET botstats:lunc with EX=259200 (3 days)",
      "/set/botstats%3Alunc" in url and "EX=259200" in url)
check("bearer token header", headers.get("Authorization") == "Bearer tok123")
body = json.loads(content)
check("payload carries bot + unix ts",
      body["bot"] == "lunc" and isinstance(body["ts"], int))
check("payload carries the counts", body["people_total"] == 5 and body["groups_member"] == 2)

print("== publish failures are swallowed ==")
check("transport failure returns False, never raises",
      asyncio.run(stats_report.publish({"people_total": 1},
                                       client_factory=lambda: FakeClient(fail=True))) is False)

print("== read_bot ==")
payload = {"bot": "garuda", "ts": int(time.time()), "groups_logging": 3}
got = asyncio.run(stats_report.read_bot(
    "garuda", client_factory=lambda: FakeClient(get_result=json.dumps(payload))))
check("fresh payload round-trips", got == payload)
check("missing key reads as None",
      asyncio.run(stats_report.read_bot(
          "garuda", client_factory=lambda: FakeClient(get_result=None))) is None)
check("corrupt payload reads as None",
      asyncio.run(stats_report.read_bot(
          "garuda", client_factory=lambda: FakeClient(get_result="{not json"))) is None)
try:
    asyncio.run(stats_report.read_bot(
        "garuda", client_factory=lambda: FakeClient(fail=True)))
    check("transport failure raises (aggregator falls back)", False)
except RuntimeError:
    check("transport failure raises (aggregator falls back)", True)

print("== freshness window (26h) ==")
now = int(time.time())
check("just-published is fresh", stats_report.is_fresh({"ts": now}, now))
check("26h old is still fresh", stats_report.is_fresh({"ts": now - 26 * 3600}, now))
check("26h+1s is stale", not stats_report.is_fresh({"ts": now - 26 * 3600 - 1}, now))
check("missing/garbled ts is stale",
      not stats_report.is_fresh({}, now) and not stats_report.is_fresh({"ts": "x"}, now)
      and not stats_report.is_fresh(None, now))
check("fmt_ts_et(0) is 'never'", stats_report.fmt_ts_et(0) == "never")
check("fmt_ts_et renders ET", stats_report.fmt_ts_et(now).endswith(" ET"))

print("== current_counts comes from the registry ==")
c = stats_report.current_counts()
for key in ("groups_member", "groups_unknown", "groups_left", "groups_active_today",
            "new_groups_today", "people_total", "people_dm_total", "people_group_total",
            "people_active_today", "dm_active_today", "new_people_today",
            "interactions_total", "interactions_command", "messages_logged",
            "pot_spent", "pot_budget", "legacy_groups"):
    check(f"current_counts has {key}", key in c)

print()
print("FAILURES:", fails if fails else "none")
sys.exit(1 if fails else 0)
