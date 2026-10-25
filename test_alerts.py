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

print()
print("FAILURES:", fails if fails else "none")
sys.exit(1 if fails else 0)
