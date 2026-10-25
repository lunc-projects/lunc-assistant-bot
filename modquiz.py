"""Captcha quiz for the group-protection gate (pure logic, no Telegram).

A new joiner in a protected group is muted and sent to the bot's DM,
where they answer safety questions plus one tap-the-right-emoji item
(the Cosmobot pattern, Luna Classic content). The questions are drawn
at random from a bank (3 of 12 per attempt, options shuffled, emoji
target varies too) so no two checks are the same — a memorized or
shared answer key doesn't pass the next person. Facts are deliberate
and unambiguous.
"""
import random

QUESTIONS = [
    {
        "q": "An 'admin' DMs you asking for your wallet seed phrase to verify your account. What do you do?",
        "options": [
            "Send it — admins are official",
            "Never share it — no real admin will ever ask for your seed phrase",
            "Send only half of the words",
        ],
        "correct": 1,
    },
    {
        "q": "A post promises to DOUBLE your LUNC if you send some first. It is…",
        "options": [
            "A normal community giveaway",
            "A scam — guaranteed doubling offers are always fake",
            "Safe if it uses the official LUNC logo",
        ],
        "correct": 1,
    },
    {
        "q": "You 'won a prize' and the site asks you to connect your wallet and approve a transaction to claim it. Best move?",
        "options": [
            "Approve quickly before the prize expires",
            "Use a spare wallet with a little in it",
            "Close it — real prizes never need you to approve wallet transactions like that",
        ],
        "correct": 2,
    },
    {
        "q": "Someone from 'LUNC Support' sends you a 'wallet validation' page and asks you to type in your seed phrase to fix an error. That page is…",
        "options": [
            "An official repair tool",
            "A phishing page — a seed phrase never gets typed into a website",
            "Safe because the link came through Telegram",
        ],
        "correct": 1,
    },
    {
        "q": "An urgent post announces an 'emergency airdrop — claim within 10 minutes or lose it.' First thing to do?",
        "options": [
            "Claim fast and check afterwards",
            "Ask in the chat and follow what the crowd does",
            "Slow down — real announcements don't need panic; verify on official channels first",
        ],
        "correct": 2,
    },
    {
        "q": "A DM says: 'I can recover your lost LUNC for a small fee, paid upfront.' It is…",
        "options": [
            "A scam — strangers can't recover lost crypto, and the upfront fee is the point",
            "A normal recovery service",
            "Worth trying with a small amount first",
        ],
        "correct": 0,
    },
    {
        "q": "Before sending LUNC to an address you got from a chat message, the safest check is…",
        "options": [
            "Trust the screenshot they posted of it",
            "Send a tiny test amount and skip checking",
            "Compare the full address against the official source, character by character",
        ],
        "correct": 2,
    },
    {
        "q": "A post shows a QR code: 'Scan to receive your reward.' Scanning unknown reward codes can…",
        "options": [
            "Deposit a reward automatically",
            "Open a wallet approval that drains you — don't scan them",
            "Just open an advertisement",
        ],
        "correct": 1,
    },
    {
        "q": "Someone helping you set up a wallet asks you to share your screen with them. You…",
        "options": [
            "Share it — they can only watch",
            "Share it but keep a hand over the seed phrase",
            "Refuse — screen sharing can expose your seed phrase and codes",
        ],
        "correct": 2,
    },
    {
        "q": "A new token uses the official LUNC name and logo and is being promoted in chats. Is it safe?",
        "options": [
            "Yes — the logo proves it's official",
            "Not necessarily — anyone can copy a name and logo; check the contract address from official sources",
            "Yes, if the mods haven't deleted the posts",
        ],
        "correct": 1,
    },
    {
        "q": "An investment 'manager' guarantees you 5% profit every week on your LUNC. Real?",
        "options": [
            "No — guaranteed crypto profits are a classic scam; real returns are never guaranteed",
            "Yes, if they show payout screenshots",
            "Yes, as long as you start small",
        ],
        "correct": 0,
    },
    {
        "q": "A Telegram message links you to a wallet app update. The safest way to update is…",
        "options": [
            "Install it straight from the link",
            "Ask the sender to confirm it's genuine",
            "Only through the official app store or the wallet's official site — never from chat links",
        ],
        "correct": 2,
    },
]

EMOJI_TARGETS = ["🍎", "🍌", "🍇", "🍓", "🍊", "🍉"]
EMOJI_POOL = ["🚗", "🐶", "⚽", "🎸", "🌙", "🍕", "✈️", "🎲"]


def build_quiz(rng=None):
    """Return 4 items: 3 questions drawn at random from the bank
    (options shuffled) + 1 emoji item with a varying target.
    Each item: {"prompt": str, "options": [str], "answer": int}."""
    rng = rng or random
    items = []
    for q in rng.sample(QUESTIONS, 3):
        opts = list(q["options"])
        right = q["options"][q["correct"]]
        rng.shuffle(opts)
        items.append({"prompt": q["q"], "options": opts, "answer": opts.index(right)})
    target = rng.choice(EMOJI_TARGETS)
    distractors = rng.sample(EMOJI_POOL, 3)
    opts = distractors + [target]
    rng.shuffle(opts)
    items.append({
        "prompt": f"Last one — tap the {target} to prove you're human.",
        "options": opts,
        "answer": opts.index(target),
    })
    return items
