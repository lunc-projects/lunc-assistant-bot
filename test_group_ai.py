"""Group AI switch tests: default ON, per-group toggle, groups independent.

Runs against a temp SQLite DB (DB_PATH env set before importing store).
"""
import os
import sys
import tempfile

tmp = tempfile.mkdtemp()
os.environ["DB_PATH"] = os.path.join(tmp, "test.db")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import store

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


check(store.ai_enabled(-100) is True, "unset group defaults to AI on")
store.set_ai_enabled(-100, False)
check(store.ai_enabled(-100) is False, "toggled off reads off")
check(store.ai_enabled(-200) is True, "another group is unaffected")
store.set_ai_enabled(-100, True)
check(store.ai_enabled(-100) is True, "toggled back on reads on")
store.set_ai_enabled(-100, False)
store.set_ai_enabled(-100, False)
check(store.ai_enabled(-100) is False, "double off stays off (idempotent)")

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
