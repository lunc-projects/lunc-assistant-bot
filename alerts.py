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


# --- Transient network errors (2026-11-11) ---
# One-off network hiccups (an LCD or Telegram read dropping) recover
# on their own, but the old code DM'd the owner for every one of
# them — twice before breakfast on 2026-11-11. Owner rule (same as
# the DO security bot going emergency-only on 2026-11-07): single
# transient network errors NEVER alert. They are counted, and only
# a genuinely persistent pattern earns ONE summary alert.
#
# Classification is by exception class name + module, walking the
# MRO and the __cause__/__context__ chain (python-telegram-bot wraps
# the underlying httpx failure inside its own NetworkError). No new
# imports: httpx/httpcore/telegram classes are recognised by name.

_TRANSIENT_CLASS_NAMES = {
    # httpx / httpcore transport + timeout + protocol errors
    "TransportError", "TimeoutException", "NetworkError",
    "ConnectError", "ReadError", "WriteError", "CloseError",
    "ConnectTimeout", "ReadTimeout", "WriteTimeout", "PoolTimeout",
    "RemoteProtocolError",
    # python-telegram-bot network failures
    "TimedOut",
}
_TRANSIENT_MODULE_PREFIXES = ("httpx", "httpcore", "telegram")
# Builtin socket-layer failures, transient wherever they surface.
_TRANSIENT_BUILTIN_NAMES = {
    "TimeoutError", "ConnectionError", "ConnectionResetError",
    "ConnectionAbortedError",
}


def is_transient_network_error(err):
    """True if err (or anything it wraps) is a transient network
    failure: a dropped read, a connect/timeout, a remote protocol
    reset, or Telegram's own NetworkError/TimedOut. Everything else
    (bugs, crashes, BadRequest, config errors) is NOT transient and
    keeps alerting immediately."""
    seen = 0
    e = err
    while e is not None and seen < 6:
        for klass in type(e).__mro__:
            name = klass.__name__
            module = getattr(klass, "__module__", "") or ""
            if name in _TRANSIENT_BUILTIN_NAMES and module == "builtins":
                return True
            if name in _TRANSIENT_CLASS_NAMES and \
                    module.startswith(_TRANSIENT_MODULE_PREFIXES):
                return True
        e = getattr(e, "__cause__", None) or getattr(e, "__context__", None)
        seen += 1
    return False


class TransientErrorTracker:
    """Counts transient network errors per class. record() returns
    a dict; 'alert' is True only when the pattern is persistent:
    >= threshold events inside `window_seconds`, OR the class has
    been recurring for `persistence_seconds`. After a summary alert,
    that class stays silent for `summary_cooldown` seconds."""

    def __init__(self, threshold=5, window_seconds=1800,
                 persistence_seconds=7200, summary_cooldown=21600):
        self.threshold = threshold
        self.window_seconds = window_seconds
        self.persistence_seconds = persistence_seconds
        self.summary_cooldown = summary_cooldown
        self._events = {}        # key -> [timestamps, last hour kept]
        self._first_seen = {}    # key -> start of the current streak
        self._last_seen = {}     # key -> most recent event time
        self._last_summary = {}  # key -> last summary alert time
        self._daily = {}         # (day_bucket, key) -> count

    def record(self, key, now):
        events = [t for t in self._events.get(key, []) if now - t < 3600]
        last = self._last_seen.get(key)
        if last is None or now - last > self.persistence_seconds:
            self._first_seen[key] = now  # long quiet gap -> new streak
        self._last_seen[key] = now
        events.append(now)
        self._events[key] = events
        day = now // 86400
        dkey = (day, key)
        self._daily[dkey] = self._daily.get(dkey, 0) + 1
        count_window = sum(1 for t in events if now - t < self.window_seconds)
        persistent = count_window >= self.threshold or \
            now - self._first_seen.get(key, now) >= self.persistence_seconds
        alert = False
        if persistent and \
                now - self._last_summary.get(key, -self.summary_cooldown) \
                >= self.summary_cooldown:
            self._last_summary[key] = now
            alert = True
        return {
            "alert": alert,
            "count_window": count_window,
            "count_hour": len(events),
            "count_today": self._daily[dkey],
        }
