"""Small bounded-retry wrapper (SANDBOX_AGENT_PLAN.md §8.5) for the call
sites where a transient failure previously killed a whole negotiation turn
outright: Gemini LLM calls (roles.py/prime.py/review.py/ownership.py/
executor.py/roster_creation).

Deliberately NOT applied to run_shell/install_package/pip subprocess calls
in executor.py -- those are the sandbox's own commands, and a real failure
there is task signal the reflect step is supposed to see and act on, not a
transient infra hiccup to paper over.
"""

import time
from typing import Callable, TypeVar

T = TypeVar("T")

DEFAULT_RETRIES = 3
DEFAULT_BACKOFF_SECONDS = 2.0


def call_with_retry(fn: Callable[[], T], *, retries: int = DEFAULT_RETRIES,
                     backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
                     label: str = "call") -> T:
    """Calls fn() up to `retries` times total, with exponential backoff
    (backoff_seconds, *2, *4, ...) between attempts. Re-raises the final
    attempt's exception if every attempt fails -- callers see the same
    exception shape as before, just after retrying instead of failing on
    the first transient hiccup."""
    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            return fn()
        except Exception as e:
            last_exc = e
            if attempt == retries:
                break
            wait = backoff_seconds * (2 ** (attempt - 1))
            print(f"    [RETRY] {label} failed (attempt {attempt}/{retries}): {e!r} "
                  f"-- retrying in {wait:.1f}s")
            time.sleep(wait)
    raise last_exc
