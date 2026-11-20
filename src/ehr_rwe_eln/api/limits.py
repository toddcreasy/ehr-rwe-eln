"""The public demo has no sign-in, so these two limits are what stand between a visitor and the
model bill: the daily token limit bounds total spend, and the per-address limit keeps one visitor
from using the whole day's allowance. Same design as glia-nav (docs/OPERATIONS.md there)."""

import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta
from datetime import time as clock_time
from zoneinfo import ZoneInfo

import psycopg
from fastapi import Request

CALLS_PER_ADDRESS_PER_HOUR = 10
_calls: dict[str, deque] = defaultdict(deque)
_calls_lock = threading.Lock()

# The day the limit counts in, so it resets at midnight US Eastern.
EASTERN = ZoneInfo("America/New_York")
TOKENS_TODAY = """
SELECT coalesce(max(tokens), 0) FROM agent.daily_usage
WHERE day = (now() AT TIME ZONE 'America/New_York')::date
"""
RECORD_CALL = """
INSERT INTO agent.daily_usage (day, tokens, calls)
VALUES ((now() AT TIME ZONE 'America/New_York')::date, %s, 1)
ON CONFLICT (day) DO UPDATE SET
    tokens = agent.daily_usage.tokens + EXCLUDED.tokens,
    calls = agent.daily_usage.calls + 1,
    updated_at = now()
"""

DAILY_LIMIT_MESSAGE = (
    "The demo has used today's agent allowance. It resets at midnight US Eastern; every page "
    "still works in the meantime."
)
ADDRESS_LIMIT_MESSAGE = "That's the hourly agent limit for the demo. Try again in a little while."


def next_reset(now: datetime | None = None) -> datetime:
    """The next midnight US Eastern, when today's allowance starts over."""
    today = (now or datetime.now(EASTERN)).astimezone(EASTERN).date()
    return datetime.combine(today + timedelta(days=1), clock_time(), tzinfo=EASTERN)


def client_address(request: Request) -> str:
    """The caller's address. The load balancer appends the address it saw to X-Forwarded-For,
    so the last entry is the one a caller cannot set."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.rsplit(",", 1)[-1].strip()
    return request.client.host if request.client else "unknown"


def within_address_limit(address: str) -> bool:
    """Counts this call if it is allowed. Held in memory, so it is per app task; the service
    runs one."""
    now = time.monotonic()
    with _calls_lock:
        times = _calls[address]
        while times and now - times[0] > 3600:
            times.popleft()
        if len(times) >= CALLS_PER_ADDRESS_PER_HOUR:
            return False
        times.append(now)
        return True


def tokens_today(con: psycopg.Connection) -> int:
    return con.execute(TOKENS_TODAY).fetchone()[0]


def record_call(con: psycopg.Connection, tokens: int) -> None:
    con.execute(RECORD_CALL, [tokens])
