"""Hashtag topic answers (Lunetta-style), Luna Classic only.

In a group, typing a hashtag like #memo makes the bot reply with a
short, ready answer. Content is static and factual — live numbers
always point at the live commands (/price, /proposals, ...). Only
tags with verified content are included; #rules, #welcome and
#commands are dynamic and handled in bot.py.
"""

TOPICS = {
    "safety": (
        "🛡 Safety rules\n"
        "• No real admin will EVER DM you first, ask for your seed phrase, or ask you to 'verify' your wallet. Ever.\n"
        "• There are no doubling giveaways and no surprise prizes that need a wallet approval.\n"
        "• Only trust links from this group's admins. Full guide: /safety"),
    "memo": (
        "🏷 About memos\n"
        "Sending LUNC to an exchange? Most exchanges use ONE shared deposit address plus a unique MEMO for your account. "
        "Forget the memo and your deposit may not arrive — recovery is slow and sometimes impossible.\n"
        "Sending between your own wallets usually needs no memo. Always send a small test first."),
    "scammed": (
        "🚨 If you were just scammed\n"
        "1. Send nothing more, and don't pay anyone who promises to 'recover' it — recovery fees are a second scam. On-chain transfers can't be reversed.\n"
        "2. If a site or person got your seed phrase, that wallet is burned forever: move anything left to a brand-new wallet with a new seed.\n"
        "3. Save tx hashes, addresses, and screenshots, and warn the group so others don't get hit."),
    "revokeaccess": (
        "🔌 Revoking access\n"
        "Terra Classic has no EVM-style approval list to revoke. What you can do: disconnect dApps inside your wallet "
        "(Station / Keplr settings → connected sites), and if you ever typed your seed phrase anywhere, treat that wallet "
        "as compromised — move funds to a fresh wallet with a new seed."),
    "scamburn": (
        "🔥 Burn-address scams\n"
        "LUNC burns happen automatically through the 1.5% burn tax on taxable transfers — nobody needs to send coins to a "
        "'burn wallet' from a DM or a random post. Any address sent to you as 'the burn address' is a trap. "
        "See the real numbers with /burn."),
    "vesting": (
        "⏳ Vesting\n"
        "Some LUNC balances unlock gradually over time instead of all at once (vesting accounts). The schedule depends on "
        "the account — check yours on LuncScan or Finder by pasting your address. Vested coins become spendable as each "
        "part unlocks; staked coins keep their own unbonding rules (21 days)."),
    "ibctransfer": (
        "🔀 IBC transfers\n"
        "IBC moves tokens between Cosmos chains (like Terra Classic ↔ Osmosis) through channels, usually inside Station. "
        "Use the exact deposit address the receiving chain gives you — a wrong chain or address format can strand funds. "
        "Always send a small test amount first. For bridging beyond Cosmos, Axelar: axelar.network"),
    "liquidstaking": (
        "💧 Liquid staking\n"
        "Liquid staking lets you stake LUNC and receive a tradeable token representing your stake, so it isn't locked. "
        "The trade-offs: smart-contract risk, the token can trade below the value of the staked LUNC, and unbonding still "
        "takes time underneath. Check who runs the contract before using one."),
    "il": (
        "⚖️ Impermanent loss (IL)\n"
        "When you provide liquidity to a pool, price moves can leave you with less value than if you'd simply held both "
        "tokens. The bigger the price swing, the bigger the gap; trading fees and rewards are what offset it. "
        "It's only locked in when you withdraw."),
    "recoverwallet": (
        "🔑 Recovering a wallet\n"
        "Restore access with your seed phrase inside Station (station.money) or Keplr (keplr.app) — use only the official "
        "sites/apps. A lost seed phrase CANNOT be recovered by anyone: anyone offering recovery for a fee is scamming. "
        "Ledger help: support.ledger.com"),
    "commonissues": (
        "🛠 Common issues\n"
        "• Tx failing? Usually gas — raise the fee/gas slightly and retry.\n"
        "• Exchange deposit missing? Check you included the MEMO (#memo).\n"
        "• 'Transport error' or wallet won't connect? It's a wallet↔chain connection issue — reconnect, or try the public endpoints (#endpoints).\n"
        "• Check any tx yourself on LuncScan by pasting its hash."),
    "wallets": (
        "👛 Wallets for Terra Classic\n"
        "Station — station.money · Keplr — keplr.app · Cosmostation — cosmostation.io\n"
        "Those are the only official sites. Look-alike domains are a top scam — type the address yourself, never follow a DM link."),
    "endpoints": (
        "🌐 Public Terra Classic endpoints\n"
        "LCD: https://terra-classic-lcd.publicnode.com\n"
        "RPC: https://terra-classic-rpc.publicnode.com\n"
        "Explorers: luncscan.com · validator.info/terra-classic"),
    "delegate": (
        "🥩 Staking / delegating\n"
        "Delegating = staking LUNC with a validator to earn rewards; unbonding takes 21 days. "
        "Step-by-step here: /stake · Validator explorer: validator.info/terra-classic · Guide: luncscan.com"),
    "validators": (
        "🏛 Validators\n"
        "Live top-10 by voting power: /validators · Full list and details: validator.info/terra-classic\n"
        "Spread your stake — delegating everything to the biggest validator isn't great for the chain."),
    "props": (
        "🗳 Governance\n"
        "Proposals voting right now: /proposals · Details and live tally: /proposal <id>\n"
        "Your vote counts through your staking wallet — the bot never votes for anyone."),
    "tokenomics": (
        "📊 LUNC numbers\n"
        "Supply, price, and market cap move constantly — get them live: /price and /stats\n"
        "Overview + exchange list: coingecko.com/en/coins/terra-luna-classic"),
    "ledger": (
        "🔐 Ledger setup\n"
        "Official guide: support.ledger.com — buy hardware wallets only from Ledger directly. "
        "Never type a Ledger seed phrase into a website or app; the device signs on its own."),
    "history": (
        "📜 Terra Classic in short\n"
        "Terra Classic is the original Terra blockchain, continued by its community after the May 2022 collapse. "
        "Its coins are LUNC and USTC. The newer, separate chain is Terra (LUNA) — different chain, different coins."),
    "links": (
        "🔗 Official links\n"
        "The short list lives here: /links — wallets, explorers, endpoints, and community references, all in one place."),
    "dex": (
        "🔄 DEXes on Luna Classic\n"
        "• Terraport — swaps, liquidity pools, farming: https://terraport.finance\n"
        "• Terraswap Classic — the original community DEX: https://app.terraswap.io\n"
        "• Garuda DeFi DEX — built natively on Terra Classic: https://garuda-defi.org\n"
        "• CL8Y DEX: https://dex.cl8y.com\n"
        "• WESO: https://wesoworld.io\n"
        "Charts for Classic pairs: Coinhall https://coinhall.org · Vyntrex https://vyntrex.io\n"
        "⚠️ Open a DEX from your own bookmark only — fake DEX sites are a common drain. Check a pair's contract address on Finder before you swap."),
}

ALIASES = {
    "safetytips": "safety", "scamwarning": "safety", "phishwarning": "safety", "nodm": "safety",
    "networks": "endpoints",
    "transporterror": "commonissues", "troubleshoot": "commonissues",
    "buyluna": "tokenomics",
    "bridging": "ibctransfer", "axelar": "ibctransfer",
    "terrastation": "wallets", "station": "wallets",
    "dexes": "dex", "swap": "dex", "trading": "dex", "exchanges": "dex",
    "ledgersetup": "ledger", "terraledger": "ledger",
    "whatisterra": "history",
}


def lookup(tag):
    """Answer text for a hashtag (without '#'), or None if unknown."""
    tag = (tag or "").lower().lstrip("#")
    if tag in TOPICS:
        return TOPICS[tag]
    canon = ALIASES.get(tag)
    return TOPICS.get(canon) if canon else None


def known(tag):
    tag = (tag or "").lower().lstrip("#")
    return tag in TOPICS or tag in ALIASES or tag in ("rules", "welcome", "commands")


def commands_text():
    tags = sorted(set(TOPICS) | set(ALIASES) | {"rules", "welcome", "commands"})
    return "🏷 Hashtags I answer in chat:\n" + " ".join("#" + t for t in tags) + "\nJust type one in the group — e.g. #memo or #scammed."
