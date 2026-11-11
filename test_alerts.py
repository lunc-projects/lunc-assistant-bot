"""Tests for the owner-alert throttler (2026-10-25).
Run: python3 test_alerts.py"""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import alerts as alerts_mod

fails = []
def check(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    if not cond: fails.append(name)

t = alerts_mod.AlertThrottler()
check("first alert goes out", t.allow("job:Timeout", 1000) is True)
check("same problem within the hour is suppressed", t.allow("job:Timeout", 2000) is False)
check("same problem after an hour alerts again", t.allow("job:Timeout", 1000 + 3601) is True)
check("different problem alerts right away", t.allow("handler:KeyError", 1500) is True)

t2 = alerts_mod.AlertThrottler()
sent = sum(1 for i in range(10) if t2.allow(f"k{i}:E", 5000))
check("global cap holds at 6 per hour", sent == 6)
check("global cap resets after the window", t2.allow("fresh:E", 5000 + 3601) is True)

# --- Transient network classification (2026-11-11) ---
def fake_err(mod, name, cause=None):
    cls = type(name, (Exception,), {"__module__": mod})
    e = cls("boom")
    if cause is not None:
        e.__cause__ = cause
    return e

check("httpx.ReadError is transient",
      alerts_mod.is_transient_network_error(fake_err("httpx", "ReadError")) is True)
check("httpx.ConnectTimeout is transient",
      alerts_mod.is_transient_network_error(fake_err("httpx", "ConnectTimeout")) is True)
check("telegram NetworkError is transient",
      alerts_mod.is_transient_network_error(fake_err("telegram.error", "NetworkError")) is True)
check("telegram TimedOut is transient",
      alerts_mod.is_transient_network_error(fake_err("telegram.error", "TimedOut")) is True)
check("wrapped httpx cause is transient",
      alerts_mod.is_transient_network_error(
          fake_err("telegram.error", "NetworkError",
                   cause=fake_err("httpx", "RemoteProtocolError"))) is True)
check("KeyError is NOT transient",
      alerts_mod.is_transient_network_error(KeyError("x")) is False)
check("telegram BadRequest is NOT transient",
      alerts_mod.is_transient_network_error(fake_err("telegram.error", "BadRequest")) is False)
check("plain ValueError is NOT transient",
      alerts_mod.is_transient_network_error(ValueError("x")) is False)

# --- Transient tracker thresholds ---
tr = alerts_mod.TransientErrorTracker()
r = tr.record("ReadError", 10000)
check("1st transient: no alert", r["alert"] is False and r["count_today"] == 1)
for i in range(3):
    r = tr.record("ReadError", 10010 + i)
check("4 in 30m: still no alert", r["alert"] is False)
r = tr.record("ReadError", 10020)
check("5th in 30m: summary alert fires", r["alert"] is True)
r = tr.record("ReadError", 10030)
check("right after summary: silenced by 6h cooldown", r["alert"] is False)

tr2 = alerts_mod.TransientErrorTracker()
tr2.record("ConnectError", 0)
r = tr2.record("ConnectError", 3600)   # sparse, but streak now 1h old
check("sparse errors under 2h: no alert", r["alert"] is False)
r = tr2.record("ConnectError", 7201)  # same streak reaches 2h
check("class still recurring after 2h: summary alert fires", r["alert"] is True)

tr3 = alerts_mod.TransientErrorTracker()
tr3.record("ReadTimeout", 0)
r = tr3.record("ReadTimeout", 100000)  # long quiet gap -> new streak
check("error after a long quiet gap starts a new streak", r["alert"] is False)

print()
print("FAILURES:", fails if fails else "none")
sys.exit(1 if fails else 0)
