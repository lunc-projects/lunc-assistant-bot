"""Tests for the simplify round's store piece: the pending-approval list
that powers tap-to-approve and number-free /approve.
Run: python3 test_simplify.py"""
import os, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_tmp = tempfile.mkdtemp()
os.environ["DB_PATH"] = os.path.join(_tmp, "test.db")

import store

fails = []
def check(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    if not cond: fails.append(name)

check("no pending at start", store.pending_groups() == [])
store.mod_request_group(-1001, "Group One", 42)
store.mod_request_group(-2002, "Group Two", 42)
check("two pending after requests", len(store.pending_groups()) == 2)
store.mod_approve_group(-1001)
pend = store.pending_groups()
check("one pending after an approval", len(pend) == 1 and pend[0]["chat_id"] == -2002)
store.mod_remove_group(-2002)  # the deny path
check("none pending after deny", store.pending_groups() == [])

print()
print("FAILURES:", fails if fails else "none")
sys.exit(1 if fails else 0)
