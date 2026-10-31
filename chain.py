"""Live Terra Classic data — all endpoints verified 2026-10-21 via PublicNode LCD + CoinGecko.
Standalone: generic public chain data only, no project-specific info."""
import base64, json, os, re, urllib.parse
import httpx
LCD = "https://terra-classic-lcd.publicnode.com"

async def _get(path):
    async with httpx.AsyncClient(timeout=25, proxy=os.getenv('OUTBOUND_PROXY') or None) as c:
        r = await c.get(f"{LCD}{path}"); r.raise_for_status(); return r.json()

async def prices():
    async with httpx.AsyncClient(timeout=25, proxy=os.getenv('OUTBOUND_PROXY') or None) as c:
        r = await c.get("https://api.coingecko.com/api/v3/simple/price?ids=terra-luna,terrausd&vs_currencies=usd&include_24hr_change=true&include_market_cap=true&include_24hr_vol=true")
        r.raise_for_status(); return r.json()

def fmt_price(d, name):
    return (f"{name}: ${d['usd']:.8g} ({d.get('usd_24h_change',0):+.2f}% 24h)\n"
            f"   Market cap: ${d.get('usd_market_cap',0):,.0f} | 24h volume: ${d.get('usd_24h_vol',0):,.0f}")

async def stats_text():
    block = await _get("/cosmos/base/tendermint/v1beta1/blocks/latest")
    height = block["block"]["header"]["height"]
    supply = await _get("/cosmos/bank/v1beta1/supply/by_denom?denom=uluna")
    total = int(supply["amount"]["amount"]) / 1e6
    pool = await _get("/cosmos/staking/v1beta1/pool")
    bonded = int(pool["pool"]["bonded_tokens"]) / 1e6
    pct = bonded / total * 100 if total else 0
    return (f"📊 *Terra Classic — live*\nBlock height: {height}\n"
            f"Total LUNC supply: {total:,.0f}\nBonded (staked): {bonded:,.0f} LUNC ({pct:.1f}% of supply)\n"
            f"Source: PublicNode LCD")

async def proposals_voting():
    d = await _get("/cosmos/gov/v1/proposals?proposal_status=2&pagination.limit=50")
    return d.get("proposals", [])

async def proposal_detail(pid):
    d = await _get(f"/cosmos/gov/v1/proposals/{pid}")
    return d["proposal"]

async def proposal_tally(pid):
    d = await _get(f"/cosmos/gov/v1/proposals/{pid}/tally")
    return d["tally"]

def tally_text(t):
    y, a, n, v = (int(t[k]) / 1e6 for k in ("yes_count", "abstain_count", "no_count", "no_with_veto_count"))
    total = y + a + n + v
    non_abstain = y + n + v
    if total == 0: return "No votes yet."
    def pc(x, base): return f"{x/base*100:.1f}%" if base else "—"
    return (f"YES {y:,.0f} ({pc(y, non_abstain)} of non-abstain)\nNO {n:,.0f}\n"
            f"NO WITH VETO {v:,.0f} ({pc(v, non_abstain)})\nABSTAIN {a:,.0f}\nTotal voted: {total:,.0f} LUNC")

async def wallet_text(addr):
    if not (addr.startswith("terra1") and len(addr) >= 39):
        return "That doesn't look like a Terra Classic address (terra1…)."
    bal = await _get(f"/cosmos/bank/v1beta1/balances/{addr}")
    lines = ["💼 *Wallet* (public on-chain data)"]
    if not bal.get("balances"): lines.append("Balances: 0 / no native balances found")
    for b in bal.get("balances", []):
        denom = {"uluna": "LUNC", "uusd": "USTC"}.get(b["denom"], b["denom"])
        amt = int(b["amount"]) / 1e6
        lines.append(f"{denom}: {amt:,.2f}")
    try:
        dels = await _get(f"/cosmos/staking/v1beta1/delegations/{addr}")
        tot = 0.0; rows = []
        for d in dels.get("delegation_responses", []):
            amt = int(d["balance"]["amount"]) / 1e6; tot += amt
            rows.append((d["delegation"]["validator_address"], amt))
        if rows:
            lines.append(f"\nStaked total: {tot:,.2f} LUNC across {len(rows)} validator(s)")
            for va, amt in rows[:10]: lines.append(f"• {va[:20]}… : {amt:,.2f}")
    except Exception: pass
    lines.append(f"\nFull history: https://finder.terra.money/classic/address/{addr}")
    lines.append("🔒 Public data only — never share a seed phrase with anyone, this bot will never ask.")
    return "\n".join(lines)

async def token_text(addr):
    q = base64.b64encode(json.dumps({"token_info": {}}).encode()).decode()
    try:
        d = await _get(f"/cosmwasm/wasm/v1/contract/{addr}/smart/{q}")
        info = d["data"]
    except Exception:
        return "Couldn't read that contract — check it's a CW20 contract address on Terra Classic."
    dec = int(info["decimals"]); supply = int(info["total_supply"]) / (10 ** dec)
    return (f"🪙 *{info['name']} ({info['symbol']})*\nDecimals: {dec}\nTotal supply: {supply:,.2f} {info['symbol']}\n"
            f"Contract: {addr}\nhttps://finder.terra.money/classic/address/{addr}\n"
            f"⚠️ Token info is on-chain data only — it does NOT verify a token is safe or legitimate. Always DYOR.")

async def validator_by_addr(valoper):
    d = await _get(f"/cosmos/staking/v1beta1/validators/{valoper}")
    return d["validator"]

async def validators_top(limit=10):
    d = await _get(f"/cosmos/staking/v1beta1/validators?status=BOND_STATUS_BONDED&pagination.limit=200")
    vals = sorted(d.get("validators", []), key=lambda v: int(v["tokens"]), reverse=True)
    return vals[:limit]

def validator_text(v):
    rate = float(v["commission"]["commission_rates"]["rate"]) * 100
    tokens = int(v["tokens"]) / 1e6
    return (f"*{v['description']['moniker']}*\nStatus: {v['status']} | Jailed: {v['jailed']}\n"
            f"Commission: {rate:.2f}% | Voting power (bonded): {tokens:,.0f} LUNC\n"
            f"Operator: {v['operator_address']}")

async def find_validator(query):
    """Search bonded+unbonded by moniker (case-insensitive substring) or exact valoper."""
    if query.startswith("terravaloper"): return await validator_by_addr(query)
    out = []
    for status in ("BOND_STATUS_BONDED", "BOND_STATUS_UNBONDED", "BOND_STATUS_UNBONDING"):
        try:
            d = await _get(f"/cosmos/staking/v1beta1/validators?status={status}&pagination.limit=300")
            out += d.get("validators", [])
        except Exception: pass
    q = query.lower()
    return next((v for v in out if q in v["description"]["moniker"].lower()), None)

def snapshot(v):
    return {"status": v["status"], "jailed": v["jailed"],
            "commission": v["commission"]["commission_rates"]["rate"], "tokens": int(v["tokens"])}

# --- Wallet Security reads (2026-10-29): full state of one wallet ---
# Every helper RAISES on failure — the wallet-watch job treats any
# failed section as "skip this wallet this cycle", never as a change.

async def _get_paged(path, list_key, limit=200, max_pages=10):
    """Follow Cosmos pagination.key until the list is complete."""
    out, key = [], None
    for _ in range(max_pages):
        sep = "&" if "?" in path else "?"
        p = f"{path}{sep}pagination.limit={limit}"
        if key: p += f"&pagination.key={key}"
        d = await _get(p)
        out += d.get(list_key, [])
        key = (d.get("pagination") or {}).get("next_key")
        if not key: break
    return out

async def bank_balances_all(addr):
    rows = await _get_paged(f"/cosmos/bank/v1beta1/balances/{addr}", "balances")
    return {r["denom"]: r["amount"] for r in rows}

async def delegations_map(addr):
    rows = await _get_paged(f"/cosmos/staking/v1beta1/delegations/{addr}", "delegation_responses")
    return {r["delegation"]["validator_address"]: r["balance"]["amount"] for r in rows}

async def unbonding_map(addr):
    rows = await _get_paged(f"/cosmos/staking/v1beta1/delegators/{addr}/unbonding_delegations", "unbonding_delegation_responses")
    out = {}
    for r in rows:
        entries = r.get("entries", [])
        total = sum(int(e["balance"]) for e in entries)
        out[r["validator_address"]] = {"total": str(total), "entries": len(entries)}
    return out

def _smart(addr, msg):
    return base64.b64encode(json.dumps(msg).encode()).decode()

async def cw20_info(contract):
    d = await _get(f"/cosmwasm/wasm/v1/contract/{contract}/smart/{_smart(contract, {'token_info': {}})}")
    return d["data"]

async def cw20_balance(contract, addr):
    d = await _get(f"/cosmwasm/wasm/v1/contract/{contract}/smart/{_smart(contract, {'balance': {'address': addr}})}")
    return d["data"]["balance"]

async def cw721_num_tokens(contract):
    d = await _get(f"/cosmwasm/wasm/v1/contract/{contract}/smart/{_smart(contract, {'num_tokens': {}})}")
    return int(d["data"]["count"])

async def cw721_contract_name(contract):
    try:
        d = await _get(f"/cosmwasm/wasm/v1/contract/{contract}/smart/{_smart(contract, {'contract_info': {}})}")
        return d["data"].get("name") or "NFT collection"
    except Exception:
        return "NFT collection"

async def cw721_tokens(contract, addr, cap=1000):
    """All token ids of `addr` in one CW721 collection (paged)."""
    out, start = [], None
    while len(out) < cap:
        q = {"tokens": {"owner": addr, "limit": 100}}
        if start: q["tokens"]["start_after"] = start
        d = await _get(f"/cosmwasm/wasm/v1/contract/{contract}/smart/{_smart(contract, q)}")
        ids = d["data"].get("tokens", [])
        if not ids: break
        out += ids; start = ids[-1]
        if len(ids) < 100: break
    return out[:cap]

async def contract_kind(contract):
    """'cw20', 'cw721' or None — decided by the contract's own
    answers, never by guessing from the address."""
    try:
        info = await cw20_info(contract)
        if "symbol" in info and "decimals" in info: return "cw20"
    except Exception: pass
    try:
        await cw721_num_tokens(contract); return "cw721"
    except Exception: return None

# --- Wallet Security tx walk (2026-10-31): per-transaction balance
# detection. A snapshot diff alone nets an in+out inside one sweep
# window into a single unexplained line; the walk lists the window's
# actual txs so each one can alert on its own line. ---

async def latest_height():
    d = await _get("/cosmos/base/tendermint/v1beta1/blocks/latest")
    return int(d["block"]["header"]["height"])

_COIN_RE = re.compile(r"^(\d+)(.+)$")

def _coin_amounts(s):
    """'15257545uluna' / '1uluna,2uusd' -> {denom: int}."""
    out = {}
    for part in str(s).split(","):
        m = _COIN_RE.match(part.strip())
        if m: out[m.group(2)] = out.get(m.group(2), 0) + int(m.group(1))
    return out

def tx_net_deltas(tx_response, address):
    """Net bank-balance effect of one tx on `address`, per denom —
    summed from the tx's own coin_received / coin_spent events.
    Fee and burn-tax spends are coin_spent events too, so the
    totals reconcile exactly with balance snapshots. Events of
    every other party (sender, fee collector, recipient) are
    ignored. Pure parsing, no network."""
    events = []
    for log in tx_response.get("logs") or []:
        events += log.get("events") or []
    if not events:
        events = tx_response.get("events") or []
    deltas = {}
    for e in events:
        t = e.get("type")
        if t not in ("coin_received", "coin_spent"): continue
        attrs = {a.get("key"): a.get("value") for a in e.get("attributes", [])}
        party = attrs.get("receiver") if t == "coin_received" else attrs.get("spender")
        if party != address: continue
        sign = 1 if t == "coin_received" else -1
        for denom, amt in _coin_amounts(attrs.get("amount", "")).items():
            deltas[denom] = deltas.get(denom, 0) + sign * amt
    return {d: v for d, v in deltas.items() if v}

async def recent_wallet_txs(addr, after_height, upto_height=None):
    """Every tx in (after_height, upto_height] that moved `addr`'s
    bank balances, oldest first: [{hash, height, deltas}]. Found
    via the wallet's own coin_received / coin_spent events, so
    sends, receives, reward claims and fee spends are all covered.
    RAISES on LCD failure — the caller falls back to plain
    snapshot diffing."""
    found = {}
    for ev, attr in (("coin_received", "receiver"), ("coin_spent", "spender")):
        q = f"{ev}.{attr}='{addr}' AND tx.height>{int(after_height)}"
        if upto_height is not None: q += f" AND tx.height<={int(upto_height)}"
        d = await _get("/cosmos/tx/v1beta1/txs?query=" + urllib.parse.quote(q) + "&order_by=ORDER_BY_ASC")
        for tr in d.get("tx_responses", []):
            found[tr["txhash"]] = tr
    out = []
    for tr in found.values():
        deltas = tx_net_deltas(tr, addr)
        if deltas:
            out.append({"hash": tr["txhash"], "height": int(tr["height"]), "deltas": deltas})
    out.sort(key=lambda t: (t["height"], t["hash"]))
    return out
