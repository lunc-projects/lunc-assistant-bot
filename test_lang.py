#!/usr/bin/env python3
"""Tests for the /language feature. Stdlib only; httpx/telegram are stubbed
because this VM doesn't install the bot's runtime deps (Railway does).
Run: python3 test_lang.py"""
import os, sys, tempfile, types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# --- Stub httpx (ai_client imports it at module level; chat() never runs here) ---
sys.modules.setdefault("httpx", types.ModuleType("httpx"))

# --- Stub telegram (lang_keyboard() imports it lazily) ---
class _Btn:
    def __init__(self, text, callback_data=None):
        self.text, self.callback_data = text, callback_data
class _Markup:
    def __init__(self, inline_keyboard):
        self.inline_keyboard = inline_keyboard
_tg = types.ModuleType("telegram")
_tg.InlineKeyboardButton = _Btn
_tg.InlineKeyboardMarkup = _Markup
sys.modules.setdefault("telegram", _tg)

# --- Store needs its DB path before import ---
_tmp = tempfile.mkdtemp()
os.environ["DB_PATH"] = os.path.join(_tmp, "test.db")

import lang
import store
import ai_client

passed = failed = 0
def check(name, cond):
    global passed, failed
    if cond: passed += 1; print(f"  ok: {name}")
    else: failed += 1; print(f"  FAIL: {name}")

print("== language table ==")
check("18 languages", len(lang.LANGS) == 18)
check("codes unique", len(lang.CODES) == len(lang.LANGS))
check("labels unique", len(set(lang.LABELS.values())) == len(lang.LANGS))
check("default is en", lang.DEFAULT == "en" and "en" in lang.CODES)
for key, table in lang.STRINGS.items():
    missing = [c for c, _, _ in lang.LANGS if not table.get(c)]
    check(f"strings[{key}] complete for all languages", not missing)
    if missing: print(f"    missing: {missing}")

print("== t() fallback ==")
check("unknown lang falls back to English", lang.t("pick", "xx") == lang.t("pick", "en"))
check("unknown key returns empty", lang.t("nope", "es") == "")
check("picked formats name", "Español" in lang.t("picked", "es", name="Español"))

print("== instruction ==")
check("en has no instruction", lang.instruction("en") == "")
check("es instruction names Spanish", "Spanish" in lang.instruction("es"))
check("unknown code has no instruction", lang.instruction("xx") == "")
check("instruction keeps addresses intact", "contract addresses" in lang.instruction("ja"))

print("== keyboard ==")
kb = lang.lang_keyboard()
buttons = [b for row in kb.inline_keyboard for b in row]
check("one button per language", len(buttons) == len(lang.LANGS))
check("callback data lang:<code>", all(b.callback_data == f"lang:{c}" for b, (c, _, _) in zip(buttons, lang.LANGS)))
check("labels are native script", all(b.text == lang.LABELS[c] for b, (c, _, _) in zip(buttons, lang.LANGS)))

print("== store round-trip ==")
check("default lang is en", store.get_user_lang(12345) == "en")
store.set_user_lang(12345, "es")
check("set/get es", store.get_user_lang(12345) == "es")
store.set_user_lang(12345, "ja")
check("overwrite to ja", store.get_user_lang(12345) == "ja")
check("other user unaffected", store.get_user_lang(99999) == "en")

print("== with_lang ==")
msgs = [{"role": "system", "content": "Base."}, {"role": "user", "content": "Hi"}]
out = ai_client.with_lang(msgs, "es")
check("appends Spanish instruction", "Spanish" in out[0]["content"] and out[0]["content"].startswith("Base."))
check("original messages not mutated", msgs[0]["content"] == "Base.")
check("en returns messages unchanged", ai_client.with_lang(msgs, "en") == msgs)
out2 = ai_client.with_lang([{"role": "user", "content": "Hi"}], "fr")
check("no-system gets one prepended", out2[0]["role"] == "system" and "French" in out2[0]["content"])

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
