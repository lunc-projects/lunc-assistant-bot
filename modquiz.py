"""Captcha quiz for the group-protection gate (pure logic, no Telegram).

A new joiner in a protected group is muted and sent to the bot's DM,
where they answer 3 short Telegram-safety questions plus one
tap-the-right-emoji item (the Cosmobot pattern, Luna Classic content).
Every item is built with shuffled options; "answer" is the index of
the correct option. Facts are deliberate and unambiguous.
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
]

EMOJI_TARGET = "🍎"
EMOJI_POOL = ["🚗", "🐶", "⚽", "🎸", "🌙", "🍕", "✈️", "🎲"]


def build_quiz(rng=None):
    """Return a list of 4 items: the 3 questions (shuffled) + 1 emoji item.
    Each item: {"prompt": str, "options": [str], "answer": int}."""
    rng = rng or random
    items = []
    qs = list(QUESTIONS)
    rng.shuffle(qs)
    for q in qs:
        opts = list(q["options"])
        right = q["options"][q["correct"]]
        rng.shuffle(opts)
        items.append({"prompt": q["q"], "options": opts, "answer": opts.index(right)})
    distractors = rng.sample(EMOJI_POOL, 3)
    opts = distractors + [EMOJI_TARGET]
    rng.shuffle(opts)
    items.append({
        "prompt": f"Last one — tap the {EMOJI_TARGET} to prove you're human.",
        "options": opts,
        "answer": opts.index(EMOJI_TARGET),
    })
    return items
