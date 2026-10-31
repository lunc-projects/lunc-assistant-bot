"""Wallet Security — pure logic (2026-10-29).

Personal wallet monitoring for the LUNC Assistant Bot: a user
registers their own Terra Classic address in DM and the bot diffs
the wallet's on-chain state about every minute, DMing an alert when
anything changes (balances, staking, unbonding, attached CW20/NFT
contracts).

This module is the pure, testable core: strict address validation,
state diffing, alert formatting. It holds NO keys, signs NOTHING,
and never talks to Telegram or the network — reading the chain is
chain.py's job, deciding what changed is this module's job. The
feature is read-only by construction.

Enumeration honesty (also stated in the bot's user copy): bank
balances, delegations and unbonding are fully enumerable from the
chain for any address. CW20 tokens and CW721 collections are NOT —
Terra Classic has no "list every contract balance of a wallet"
query — so token/NFT watching covers exactly the contracts the
user attaches with /watch <contract address>, nothing hidden.
"""
import hashlib
import json
import re

# --- Limits (also enforced in store.py / bot.py) ---
MAX_WALLETS_PER_USER = 3
MAX_CONTRACTS_PER_USER = 10
NFT_TOKEN_CAP = 1000          # per collection per wallet, per cycle
DEDUPE_WINDOW_SECONDS = 24 * 3600

# --- bech32 (BIP-173) verification ---
_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
_CHARSET_REV = {c: i for i, c in enumerate(_CHARSET)}


def _polymod(values):
    chk = 1
    gen = (0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)
    for v in values:
        top = chk >> 25
        chk = ((chk & 0x1FFFFFF) << 5) ^ v
        for i in range(5):
            if (top >> i) & 1:
                chk ^= gen[i]
    return chk


def _hrp_expand(hrp):
    return [ord(x) >> 5 for x in hrp] + [0] + [ord(x) & 31 for x in hrp]


def bech32_verify(addr):
    """True iff addr is a well-formed bech32 string with a valid
    checksum. (BIP-173 constant 1; Terra Classic uses bech32, not
    bech32m.)"""
    if not isinstance(addr, str) or len(addr) < 8 or len(addr) > 90:
        return False
    # Terra addresses are lowercase bech32; callers enforce the
    # lowercase terra1 shape (_terra_shape) before this is reached.
    if any(ord(c) < 33 or ord(c) > 126 for c in addr):
        return False
    pos = addr.rfind("1")
    if pos < 1 or pos + 7 > len(addr):
        return False
    hrp, data_part = addr[:pos], addr[pos + 1:]
    if any(c not in _CHARSET_REV for c in data_part):
        return False
    data = [_CHARSET_REV[c] for c in data_part]
    return _polymod(_hrp_expand(hrp) + data) == 1


def _terra_shape(addr, total_len):
    """Strict Terra shape: exact length, terra1 prefix, valid bech32
    checksum, payload length matching the address class."""
    if not isinstance(addr, str):
        return False
    addr = addr.strip()
    if len(addr) != total_len or not addr.startswith("terra1"):
        return False
    if addr != addr.lower():
        return False
    return bech32_verify(addr)


def validate_account_address(addr):
    """A Terra Classic account address: 44 chars (20-byte payload)."""
    return _terra_shape(addr, 44)


def validate_contract_address(addr):
    """A Terra Classic contract address: 64 chars (32-byte payload)."""
    return _terra_shape(addr, 64)


# Injection-shaped / junk inputs never reach SQL: anything that is
# not exactly one of the two shapes above is rejected by the
# validators before any store call. This regex is a second belt for
# free-text fields: terra-ish strings only.
TERRA_TEXT_RE = re.compile(r"^terra1[qpzry9x8gf2tvdw0s3jn54khce6mua7l]+$")


# --- Amount formatting ---
DENOM_DISPLAY = {"uluna": ("LUNC", 6), "uusd": ("USTC", 6)}


def fmt_amount(raw, decimals):
    """Raw integer string -> grouped decimal string."""
    try:
        v = int(raw)
    except Exception:
        return str(raw)
    dec = int(decimals)
    if dec <= 0:
        return f"{v:,}"
    sign = "-" if v < 0 else ""
    v = abs(v)
    whole, frac = divmod(v, 10 ** dec)
    if frac:
        frac_s = f"{frac:0{dec}d}".rstrip("0")
        return f"{sign}{whole:,}.{frac_s}"
    return f"{sign}{whole:,}"


def fmt_delta(old_raw, new_raw, decimals):
    d = int(new_raw) - int(old_raw)
    s = fmt_amount(abs(d), decimals)
    return ("+" if d > 0 else "-") + s


# --- State diffing ---
# State shape (all amounts raw integer strings):
# {
#   "balances":    {denom: amount},
#   "delegations": {valoper: amount_uluna},
#   "unbonding":   {valoper: {"total": amount, "entries": n}},
#   "cw20":        {contract: {"balance": amount, "symbol": s, "decimals": d}},
#   "nfts":        {contract: {"name": s, "tokens": [ids...]}},
# }

def _chg(kind, key, **kw):
    d = {"kind": kind, "key": key}
    d.update(kw)
    return d


def diff_states(old, new):
    """Return the list of changes between two state snapshots.
    Empty list = nothing changed. A missing/empty old snapshot
    yields [] — a first sighting is a baseline, NEVER an alert."""
    if not old:
        return []
    changes = []

    ob, nb = old.get("balances", {}), new.get("balances", {})
    for denom in sorted(set(ob) | set(nb)):
        o, n = ob.get(denom), nb.get(denom)
        if o != n:
            changes.append(_chg("balance", denom, old=o or "0", new=n or "0"))

    od, nd = old.get("delegations", {}), new.get("delegations", {})
    for valoper in sorted(set(od) | set(nd)):
        o, n = od.get(valoper), nd.get(valoper)
        if o != n:
            changes.append(_chg("delegation", valoper, old=o or "0", new=n or "0"))

    ou, nu = old.get("unbonding", {}), new.get("unbonding", {})
    for valoper in sorted(set(ou) | set(nu)):
        o, n = ou.get(valoper), nu.get(valoper)
        ot = (o or {}).get("total", "0")
        nt = (n or {}).get("total", "0")
        if ot != nt or (o or {}).get("entries") != (n or {}).get("entries"):
            changes.append(_chg("unbonding", valoper, old=ot, new=nt))

    oc, nc = old.get("cw20", {}), new.get("cw20", {})
    for contract in sorted(set(oc) | set(nc)):
        o, n = oc.get(contract), nc.get(contract)
        obal = (o or {}).get("balance", "0")
        nbal = (n or {}).get("balance", "0")
        if obal != nbal:
            meta = n or o or {}
            changes.append(_chg("cw20", contract, old=obal, new=nbal,
                                symbol=meta.get("symbol", "?"),
                                decimals=meta.get("decimals", 6)))

    on, nn = old.get("nfts", {}), new.get("nfts", {})
    for contract in sorted(set(on) | set(nn)):
        o, n = on.get(contract), nn.get(contract)
        otoks = set((o or {}).get("tokens", []))
        ntoks = set((n or {}).get("tokens", []))
        meta = n or o or {}
        for tid in sorted(ntoks - otoks):
            changes.append(_chg("nft_in", contract, token=tid,
                                name=meta.get("name", "NFT collection")))
        for tid in sorted(otoks - ntoks):
            changes.append(_chg("nft_out", contract, token=tid,
                                name=meta.get("name", "NFT collection")))
    return changes


# --- Per-transaction balance changes (2026-10-31) ---
# A snapshot diff nets everything inside one sweep window into a
# single per-denom line — an in and an out in the same window used
# to surface as one unexplained net figure (+98,500 in and
# -10,015.257545 out read as a single +88,484.74 line). When the
# sweep walks the window's actual txs (chain.recent_wallet_txs),
# balance changes are rebuilt per transaction instead: one line
# per tx, running old->new totals, each line carrying its tx hash
# (Finder link in the alert, per-tx dedupe via change_key). The
# rebuild is accepted per denom ONLY when the tx lines land
# exactly on the new snapshot — a partial walk (a tx the LCD
# didn't return, a read race) falls back to the plain netted line
# for that denom, so an alert's totals always reconcile with the
# snapshot it was diffed from.

def tx_balance_changes(old_balances, new_balances, txs):
    """'balance' change dicts built from the window's txs.
    txs: [{hash, height, deltas:{denom: signed int}}], oldest
    first. A denom the txs touch alerts even when its net over
    the window is zero — an in and an out of the same size are
    two changes, not none."""
    denoms = set(old_balances) | set(new_balances)
    for tx in txs:
        denoms |= {d for d, v in (tx.get("deltas") or {}).items() if v}
    out = []
    for denom in sorted(denoms):
        o = int(old_balances.get(denom) or 0)
        n = int(new_balances.get(denom) or 0)
        running, lines = o, []
        for tx in txs:
            dv = int((tx.get("deltas") or {}).get(denom) or 0)
            if not dv: continue
            lines.append(_chg("balance", denom, old=str(running),
                              new=str(running + dv), tx=tx["hash"],
                              height=tx["height"]))
            running += dv
        if lines and running == n:
            out += lines
        elif o != n:
            out.append(_chg("balance", denom, old=str(o), new=str(n)))
    return out


def merge_tx_changes(changes, old, new, txs):
    """Swap a diff_states result's balance section for the
    per-transaction rebuild, keeping every other section as
    diffed. txs=None (the walk failed, or the stored snapshot
    predates height watermarks) returns the diff untouched."""
    if txs is None:
        return changes
    rest = [c for c in changes if c["kind"] != "balance"]
    return tx_balance_changes(old.get("balances", {}),
                              new.get("balances", {}), txs) + rest


def change_key(change):
    """Stable hash for duplicate suppression: same change to the
    same wallet section never alerts twice inside the window."""
    raw = json.dumps(change, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


# --- Alert formatting ---
FINDER = "https://finder.terraclassic.community/mainnet"


def _bal_label(denom):
    return DENOM_DISPLAY.get(denom, (denom, 6))


def format_alert(address, changes, away=False):
    """One DM per wallet per cycle: what changed, with amounts and
    full clickable finder links. Plain text (no markdown) so an
    odd token symbol can never break formatting. away=True labels
    the changes as found on return after downtime (they happened
    while the watcher was offline and are caught by the first
    post-restart diff against the stored baseline)."""
    head = ("🛡️ Wallet Security — change detected while I was away (found on return)"
            if away else "🛡️ Wallet Security — change detected")
    lines = [head,
             f"Wallet: {address}",
             f"View: {FINDER}/account/{address}", ""]
    for c in changes[:12]:
        k = c["kind"]
        if k == "balance":
            sym, dec = _bal_label(c["key"])
            lines.append(f"• {sym} balance: {fmt_amount(c['old'], dec)} → "
                         f"{fmt_amount(c['new'], dec)} ({fmt_delta(c['old'], c['new'], dec)} {sym})")
            if c.get("tx"):
                lines.append(f"  Tx: {FINDER}/tx/{c['tx']}")
        elif k == "delegation":
            lines.append(f"• Staked with {c['key']}: {fmt_amount(c['old'], 6)} → "
                         f"{fmt_amount(c['new'], 6)} LUNC ({fmt_delta(c['old'], c['new'], 6)})")
            lines.append(f"  Validator: {FINDER}/validator/{c['key']}")
        elif k == "unbonding":
            lines.append(f"• Unbonding from {c['key']}: {fmt_amount(c['old'], 6)} → "
                         f"{fmt_amount(c['new'], 6)} LUNC")
        elif k == "cw20":
            dec = c.get("decimals", 6)
            lines.append(f"• {c.get('symbol', '?')} token balance: {fmt_amount(c['old'], dec)} → "
                         f"{fmt_amount(c['new'], dec)} ({fmt_delta(c['old'], c['new'], dec)})")
            lines.append(f"  Token: {FINDER}/account/{c['key']}")
        elif k == "nft_in":
            lines.append(f"• NFT received: {c.get('name', 'NFT')} #{c['token']}")
            lines.append(f"  Collection: {FINDER}/account/{c['key']}")
        elif k == "nft_out":
            lines.append(f"• NFT left wallet: {c.get('name', 'NFT')} #{c['token']}")
            lines.append(f"  Collection: {FINDER}/account/{c['key']}")
    if len(changes) > 12:
        lines.append(f"…and {len(changes) - 12} more change(s) — check the wallet link above.")
    lines.append("")
    lines.append("If you didn't make this change, treat it as a security issue: "
                 "check the wallet on Finder right away. This bot only watches — "
                 "it cannot move or recover funds.")
    return "\n".join(lines)
