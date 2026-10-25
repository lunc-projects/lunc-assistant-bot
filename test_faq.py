"""Tests for the per-group FAQ store functions. Run: python3 test_faq.py"""
import os, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_tmp = tempfile.mkdtemp()
os.environ["DB_PATH"] = os.path.join(_tmp, "test.db")

import store

fails = []
def check(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    if not cond: fails.append(name)

check("no answer before add", store.faq_get(-1001, "where do i stake") is None)
check("list empty before add", store.faq_list(-1001) == [])
store.faq_add(-1001, "where do i stake", "Use /stake for the steps.", 42)
check("answer roundtrip", store.faq_get(-1001, "where do i stake") == "Use /stake for the steps.")
check("per-group isolation", store.faq_get(-2002, "where do i stake") is None)
store.faq_add(-1001, "when is the call", "Fridays 7pm ET.", 42)
check("list shows both, sorted", store.faq_list(-1001) == ["when is the call", "where do i stake"])
store.faq_add(-1001, "where do i stake", "Updated answer.", 43)
check("re-adding updates the answer", store.faq_get(-1001, "where do i stake") == "Updated answer.")
check("still one row for it", store.faq_list(-1001).count("where do i stake") == 1)
check("remove works", store.faq_remove(-1001, "when is the call") == 1)
check("removed answer gone", store.faq_get(-1001, "when is the call") is None)
check("remove again is a no-op", store.faq_remove(-1001, "when is the call") == 0)

print()
print("FAILURES:", fails if fails else "none")
sys.exit(1 if fails else 0)
