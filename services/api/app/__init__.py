"""Bunnelby API application package.

The desktop product runs one local API process. Approval execution is serialized here as
an in-process safety guard in addition to the durable database compare-and-set checks.
This closes same-process double-click/concurrent-request races on SQLite without changing
the approval schema or weakening the exactly-once/idempotency protections.
"""

from __future__ import annotations

import threading
from functools import wraps

from . import approval_service as approval_service

_APPROVAL_EXECUTION_LOCK = threading.RLock()


def _serialize_approval_execution(function):
    @wraps(function)
    def guarded(*args, **kwargs):
        with _APPROVAL_EXECUTION_LOCK:
            return function(*args, **kwargs)

    return guarded


# Guard both public execution entry points and the dispatcher. RLock is intentional:
# approve_and_execute delegates to one of these functions while already holding the guard.
approval_service.send_approved_email = _serialize_approval_execution(
    approval_service.send_approved_email
)
approval_service.create_approved_calendar_event = _serialize_approval_execution(
    approval_service.create_approved_calendar_event
)
approval_service.approve_and_execute = _serialize_approval_execution(
    approval_service.approve_and_execute
)
