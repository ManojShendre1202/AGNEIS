"""Lightweight in-process TPM/RPM guard for Gemini calls -- not a queue or
scheduler, just a sliding-window check each call site waits on before firing,
so a burst of negotiation turns doesn't blow through the API's per-minute
quota. Token counts are a cheap chars/4 estimate before the call, corrected
with the real usage_metadata afterward -- exact enough for a guard, not for
billing.

Defaults are conservative free-tier guesses, not a real quota lookup --
override via AGNIES_GEMINI_RPM / AGNIES_GEMINI_TPM once you know your actual
tier's numbers. Either set to 0 disables that dimension's guard.
"""

import os
import threading
import time

_WINDOW_SECONDS = 60.0


class RateLimiter:
    def __init__(self, rpm: int, tpm: int):
        self.rpm = rpm
        self.tpm = tpm
        self._request_times: list[float] = []
        self._token_events: list[tuple[float, int]] = []
        self._lock = threading.Lock()

    def _prune(self, now: float) -> None:
        cutoff = now - _WINDOW_SECONDS
        self._request_times = [t for t in self._request_times if t > cutoff]
        self._token_events = [(t, n) for t, n in self._token_events if t > cutoff]

    def acquire(self, estimated_tokens: int, label: str = "call") -> None:
        if self.rpm <= 0 and self.tpm <= 0:
            return
        while True:
            with self._lock:
                now = time.time()
                self._prune(now)
                tokens_in_window = sum(n for _, n in self._token_events)
                over_rpm = self.rpm > 0 and len(self._request_times) >= self.rpm
                over_tpm = self.tpm > 0 and tokens_in_window + estimated_tokens > self.tpm
                if not over_rpm and not over_tpm:
                    self._request_times.append(now)
                    return
                candidates = []
                if over_rpm and self._request_times:
                    candidates.append(self._request_times[0])
                if over_tpm and self._token_events:
                    candidates.append(self._token_events[0][0])
                oldest = min(candidates) if candidates else now
                wait = max(0.5, _WINDOW_SECONDS - (now - oldest))
            print(f"    [RATE LIMIT] {label} waiting {wait:.1f}s "
                  f"(rpm_limit={self.rpm} tpm_limit={self.tpm})")
            time.sleep(wait)

    def record(self, actual_tokens: int) -> None:
        if self.rpm <= 0 and self.tpm <= 0:
            return
        with self._lock:
            self._token_events.append((time.time(), max(actual_tokens, 0)))


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


GEMINI_RATE_LIMITER = RateLimiter(
    rpm=_int_env("AGNIES_GEMINI_RPM", 15),
    tpm=_int_env("AGNIES_GEMINI_TPM", 250_000),
)


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)
