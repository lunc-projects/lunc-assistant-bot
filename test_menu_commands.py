"""Command-menu tests (2026-11-11): the Telegram menu comes from the
set_my_commands list in post_init (bot.py), NOT from the registered
handlers — /translate shipped with a working handler + /help line but
no menu entry, and Tom couldn't find it ("Don't see it"). These checks
parse bot.py so the miss class is caught: every command the menu
advertises must exist in the list AND have a CommandHandler, and
/translate specifically must stay in the menu.

Static parse only — no bot import, no network.
Run: python3 test_menu_commands.py"""
import ast
import os
import re
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = open(os.path.join(ROOT, "bot.py"), encoding="utf-8").read()
TREE = ast.parse(SRC)

passed = 0
failed = 0


def check(cond, msg):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ok: {msg}")
    else:
        failed += 1
        print(f"FAIL: {msg}")


# --- The registered menu: the list handed to set_my_commands ---
menu_calls = [
    node for node in ast.walk(TREE)
    if isinstance(node, ast.Call)
    and isinstance(node.func, ast.Attribute)
    and node.func.attr == "set_my_commands"
]
check(len(menu_calls) == 1,
      f"exactly one set_my_commands call in bot.py (found {len(menu_calls)})")

menu = []
if menu_calls and menu_calls[0].args:
    for elt in menu_calls[0].args[0].elts:
        cmd, desc = ast.literal_eval(elt)
        menu.append((cmd, desc))
menu_cmds = [c for c, _ in menu]
check(len(menu) > 30, f"menu parsed ({len(menu)} entries)")

# --- The handlers: every CommandHandler("name", ...) in bot.py ---
handler_cmds = {
    node.args[0].value for node in ast.walk(TREE)
    if isinstance(node, ast.Call) and node.args
    and isinstance(node.args[0], ast.Constant)
    and isinstance(node.args[0].value, str)
    and ((isinstance(node.func, ast.Name) and node.func.id == "CommandHandler")
         or (isinstance(node.func, ast.Attribute) and node.func.attr == "CommandHandler"))
}
check(len(handler_cmds) > 30, f"handlers parsed ({len(handler_cmds)} commands)")

# --- The regression itself ---
check("translate" in menu_cmds, "/translate is in the registered menu list")
check("translate" in handler_cmds, "/translate has a CommandHandler")

# --- Menu-wide consistency: no advertised command may be a dead end ---
missing = [c for c in menu_cmds if c not in handler_cmds]
check(not missing, f"every menu command has a handler (missing: {missing})")
check(len(menu_cmds) == len(set(menu_cmds)), "menu commands are unique")

cmd_re = re.compile(r"^[a-z0-9_]{1,32}$")
bad_names = [c for c in menu_cmds if not cmd_re.match(c)]
check(not bad_names, f"menu command names are Telegram-valid (bad: {bad_names})")
bad_desc = [c for c, d in menu if not (1 <= len(d) <= 256)]
check(not bad_desc, f"menu descriptions are 1-256 chars (bad: {bad_desc})")

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
