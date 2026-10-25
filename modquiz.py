"""Human check for the group-protection gate (pure logic, no Telegram).

Owner's direction (2026-10-25): the gate's job is basic security —
prove the joiner is a real person so bot accounts can't get in.
It is NOT a knowledge test: regular people may not know crypto
safety answers, and a check they can't pass locks out the very
members the group wants. So every item is a dead-simple tap any
human gets instantly — tap the named emoji, a tiny sum, pick the
animal / the food, the biggest number — with the content randomized
per attempt so scripts and shared answers don't help. Safety
teaching still happens elsewhere (the pass message, /scamalerts,
#safety); this gate only checks "human".
"""
import random

TAP_TARGETS = ["🍎", "🍌", "🍇", "🍓", "🍊", "🍉", "🍕", "🐶", "⭐", "🚗", "🎸", "⚽"]
EMOJI_POOL = ["🚗", "🐶", "⚽", "🎸", "🌙", "🍕", "✈️", "🎲", "📱", "⌚", "🎧", "🔑",
              "📚", "🍩", "🧲", "🦊", "🍔", "🌮", "🍦", "🥕", "🐱", "🐰", "🐸"]
ANIMALS = ["🐶", "🐱", "🐰", "🦊", "🐸", "🐵", "🐷", "🦁"]
NON_ANIMALS = ["🚗", "⚽", "🎸", "🌙", "🍕", "✈️", "🎲", "📱", "⌚", "🎧", "🔑", "📚"]
FOODS = ["🍕", "🍔", "🍎", "🍩", "🍇", "🌮", "🍦", "🥕"]
NON_FOODS = ["🚗", "⚽", "🎸", "🌙", "✈️", "🎲", "📱", "⌚", "🎧", "🔑", "📚", "🧦"]


def _mk(prompt, options, right, rng):
    opts = list(options)
    rng.shuffle(opts)
    return {"prompt": prompt, "options": opts, "answer": opts.index(right)}


def _check_tap(rng):
    target = rng.choice(TAP_TARGETS)
    distract = rng.sample([e for e in EMOJI_POOL if e != target], 3)
    return _mk(f"Tap the {target}", distract + [target], target, rng)


def _check_math(rng):
    a, b = rng.randint(1, 9), rng.randint(1, 9)
    s = a + b
    wrongs = rng.sample([x for x in (s - 2, s - 1, s + 1, s + 2, s + 3) if x > 0], 2)
    return _mk(f"Quick math: what is {a} + {b}?", [str(s)] + [str(w) for w in wrongs], str(s), rng)


def _check_animal(rng):
    a = rng.choice(ANIMALS)
    return _mk("Which one is an animal?", rng.sample(NON_ANIMALS, 3) + [a], a, rng)


def _check_food(rng):
    f = rng.choice(FOODS)
    return _mk("Which one can you eat?", rng.sample(NON_FOODS, 3) + [f], f, rng)


def _check_biggest(rng):
    nums = rng.sample(range(3, 90), 3)
    big = str(max(nums))
    return _mk("Tap the biggest number", [str(n) for n in nums], big, rng)


BUILDERS = [_check_tap, _check_math, _check_animal, _check_food, _check_biggest]


def build_quiz(rng=None):
    """Return 4 simple human checks (distinct kinds, content randomized).
    Each item: {"prompt": str, "options": [str], "answer": int}."""
    rng = rng or random
    return [kind(rng) for kind in rng.sample(BUILDERS, 4)]
