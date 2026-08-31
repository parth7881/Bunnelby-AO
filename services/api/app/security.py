from __future__ import annotations

import os
from collections import deque
from typing import Final

from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


DEFAULT_MAX_REQUEST_BODY_BYTES: Final[int] = 16 * 1024 * 1024
ALLOWED_BROWSER_ORIGINS: Final[frozenset[str]] = frozenset(
    {
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    }
)
TRUSTED_HOSTS: Final[list[str]] = ["127.0.0.1", "localhost", "testserver"]

_SECURITY_HEADERS: Final[tuple[tuple[bytes, bytes], ...]] = (
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"cache-control", b"no-store"),
    (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'; base-uri 'none'"),
)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().casefold() in {"1", "true", "yes", "on"}


def api_docs_enabled() -> bool:
    """Interactive API discovery is opt-in; production/local desktop defaults closed."""
    return _env_bool("BUNNELBY_API_DOCS", False)


def max_request_body_bytes() -> int:
    raw = os.getenv("BUNNELBY_MAX_REQUEST_BODY_BYTES", "").strip()
    if not raw:
        return DEFAULT_MAX_REQUEST_BODY_BYTES
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MAX_REQUEST_BODY_BYTES
    # Prevent an environment typo from disabling the global DoS boundary.
    return max(64 * 1024, min(value, 32 * 1024 * 1024))


def _scope_headers(scope: Scope) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw_name, raw_value in scope.get("headers", []):
        name = raw_name.decode("latin-1").casefold()
        # Duplicate security-relevant request headers are ambiguous. Preserve the first value;
        # callers reject comma-joined/invalid values rather than accepting attacker overrides.
        result.setdefault(name, raw_value.decode("latin-1").strip())
    return result


def _browser_request_is_allowed(headers: dict[str, str]) -> bool:
    origin = headers.get("origin", "").strip()
    if origin and origin not in ALLOWED_BROWSER_ORIGINS:
        return False

    # Fetch Metadata is set by modern browsers and is useful against drive-by localhost CSRF.
    # Non-browser local clients (CLI probes/tests/runtime supervisor) commonly omit it and are
    # still allowed until the per-launch authenticated IPC/API channel is introduced.
    fetch_site = headers.get("sec-fetch-site", "").strip().casefold()
    if fetch_site == "cross-site":
        return False
    return True


def _append_security_headers(message: Message) -> Message:
    if message.get("type") != "http.response.start":
        return message

    # ASGI header names are bytes. Header names are ASCII case-insensitive, so bytes.lower()
    # is the correct normalization and avoids decoding/re-encoding response metadata.
    existing = {
        name.lower()
        for name, _ in message.get("headers", [])
    }
    headers = list(message.get("headers", []))
    for name, value in _SECURITY_HEADERS:
        if name not in existing:
            headers.append((name, value))
    message["headers"] = headers
    return message


class LocalAPISecurityMiddleware:
    """Fail-closed browser/size boundary for Bunnelby's loopback FastAPI surface.

    This middleware is deliberately independent of the LLM/orchestrator. Model output cannot
    relax it. It blocks hostile browser origins / Fetch Metadata, enforces a bounded request
    body even for chunked requests, and adds non-cacheable defensive response headers.

    A local process can still open a raw loopback socket, so this is not treated as local API
    authentication. The stronger per-launch IPC/session-token boundary is a separate atomic
    migration and must not be approximated with a hard-coded token.
    """

    def __init__(self, app: ASGIApp, *, max_body_bytes: int | None = None) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes or max_request_body_bytes()

    async def _reject(self, scope: Scope, receive: Receive, send: Send, status_code: int) -> None:
        response = PlainTextResponse(
            "Request rejected.",
            status_code=status_code,
            headers={
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Referrer-Policy": "no-referrer",
            },
        )
        await response(scope, receive, send)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        headers = _scope_headers(scope)
        if not _browser_request_is_allowed(headers):
            await self._reject(scope, receive, send, 403)
            return

        raw_length = headers.get("content-length", "")
        if raw_length:
            try:
                declared_length = int(raw_length)
            except ValueError:
                await self._reject(scope, receive, send, 400)
                return
            if declared_length < 0 or declared_length > self.max_body_bytes:
                await self._reject(scope, receive, send, 413)
                return

        # Do not trust Content-Length alone: read and replay the bounded ASGI body so chunked
        # requests cannot bypass the limit. Memory use is capped by max_body_bytes.
        buffered: deque[Message] = deque()
        total = 0
        while True:
            message = await receive()
            buffered.append(message)
            if message.get("type") == "http.request":
                total += len(message.get("body", b""))
                if total > self.max_body_bytes:
                    await self._reject(scope, receive, send, 413)
                    return
                if not message.get("more_body", False):
                    break
            elif message.get("type") == "http.disconnect":
                break

        async def replay_receive() -> Message:
            if buffered:
                return buffered.popleft()
            return {"type": "http.disconnect"}

        async def secure_send(message: Message) -> None:
            await send(_append_security_headers(message))

        await self.app(scope, replay_receive, secure_send)
