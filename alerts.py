"""Owner alert throttling for the LUNC Assistant Bot (2026-10-25).

When something goes wrong inside the bot, the owner gets a DM — but
a repeating failure (a background job erroring every minute) must
not turn into alert spam. Rules:
- the same kind of problem alerts at most once per hour;
- total alerts are capped per rolling hour;
- record() is only called for an alert that will actually be sent,
  so suppressed problems stay suppressed until their window passes.
Pure and time-injected, so it's unit-testable.
"""


class AlertThrottler:
    def __init__(self, per_key_seconds=3600, global_max=6, global_window=3600):
        self.per_key_seconds = per_key_seconds
        self.global_max = global_max
        self.global_window = global_window
        self._last_by_key = {}
        self._sent = []

    def allow(self, key, now):
        """True (and records the send) if this alert may go out."""
        self._sent = [t for t in self._sent if now - t < self.global_window]
        last = self._last_by_key.get(key)
        if last is not None and now - last < self.per_key_seconds:
            return False
        if len(self._sent) >= self.global_max:
            return False
        self._last_by_key[key] = now
        self._sent.append(now)
        return True
