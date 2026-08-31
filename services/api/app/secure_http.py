from __future__ import annotations

import http.client
import re
import ssl
from dataclasses import dataclass
from typing import Final, Mapping
from urllib.parse import urljoin, urlsplit


_MAX_URL_LENGTH: Final[int] = 2048
_MAX_TIMEOUT_SECONDS: Final[float] = 120.0
_REDIRECT_STATUSES: Final[frozenset[int]] = frozenset({301, 302, 303, 307, 308})
_HEADER_NAME_RE: Final[re.Pattern[str]] = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
_SENSITIVE_REDIRECT_HEADERS: Final[frozenset[str]] = frozenset(
    {"authorization", "cookie", "proxy-authorization"}
)


class SecureHTTPError(RuntimeError):
    """Raised when an outbound HTTPS request violates policy or transport bounds."""


@dataclass(frozen=True)
class SecureHTTPResponse:
    status: int
    headers: tuple[tuple[str, str], ...]
    body: bytes
    url: str


def _contains_control_characters(value: str) -> bool:
    return any(ord(char) < 32 or ord(char) == 127 for char in value)


def _normalize_allowed_hosts(allowed_hosts: frozenset[str] | set[str] | tuple[str, ...]) -> frozenset[str]:
    normalized = frozenset(host.strip().casefold().rstrip(".") for host in allowed_hosts if host.strip())
    if not normalized:
        raise SecureHTTPError("At least one outbound HTTPS host must be explicitly allowed.")
    return normalized


def _validate_url(url: str, allowed_hosts: frozenset[str]) -> tuple[str, str]:
    if not isinstance(url, str) or not url or len(url) > _MAX_URL_LENGTH:
        raise SecureHTTPError("Outbound URL is invalid or too long.")
    if _contains_control_characters(url):
        raise SecureHTTPError("Outbound URL contains control characters.")

    parsed = urlsplit(url)
    if parsed.scheme.casefold() != "https":
        raise SecureHTTPError("Only HTTPS outbound URLs are allowed.")
    if parsed.username is not None or parsed.password is not None:
        raise SecureHTTPError("Credentials in outbound URLs are forbidden.")
    if parsed.fragment:
        raise SecureHTTPError("Fragments are not allowed in outbound request URLs.")

    host = (parsed.hostname or "").casefold().rstrip(".")
    if not host or host not in allowed_hosts:
        raise SecureHTTPError("Outbound host is not allow-listed.")
    try:
        port = parsed.port
    except ValueError as exc:
        raise SecureHTTPError("Outbound URL contains an invalid port.") from exc
    if port not in (None, 443):
        raise SecureHTTPError("Only the default HTTPS port is allowed.")

    target = parsed.path or "/"
    if parsed.query:
        target = f"{target}?{parsed.query}"
    return host, target


def _validate_headers(headers: Mapping[str, str] | None) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw_name, raw_value in (headers or {}).items():
        name = str(raw_name).strip()
        value = str(raw_value)
        if not name or not _HEADER_NAME_RE.fullmatch(name):
            raise SecureHTTPError("Outbound request contains an invalid header name.")
        if _contains_control_characters(value):
            raise SecureHTTPError("Outbound request contains an invalid header value.")
        if name.casefold() in {"host", "content-length", "transfer-encoding"}:
            raise SecureHTTPError(f"Outbound header {name!r} is managed by the HTTP transport.")
        result[name] = value
    return result


def _read_bounded_response(response: http.client.HTTPResponse, max_response_bytes: int) -> bytes:
    raw_length = response.getheader("Content-Length")
    if raw_length:
        try:
            declared_length = int(raw_length)
        except ValueError as exc:
            raise SecureHTTPError("Remote server returned an invalid Content-Length.") from exc
        if declared_length < 0 or declared_length > max_response_bytes:
            raise SecureHTTPError("Remote response exceeds the configured size limit.")

    body = response.read(max_response_bytes + 1)
    if len(body) > max_response_bytes:
        raise SecureHTTPError("Remote response exceeds the configured size limit.")
    return body


def request_https(
    url: str,
    *,
    allowed_hosts: frozenset[str] | set[str] | tuple[str, ...],
    method: str = "GET",
    headers: Mapping[str, str] | None = None,
    body: bytes | None = None,
    timeout_seconds: float = 30.0,
    max_response_bytes: int = 2 * 1024 * 1024,
    max_request_bytes: int = 1024 * 1024,
    max_redirects: int = 0,
) -> SecureHTTPResponse:
    """Perform a bounded TLS-verified request to an explicit hostname allow-list.

    This is intentionally narrower than a general URL client. It rejects non-HTTPS
    schemes, embedded credentials, custom ports, unsafe headers, oversized payloads,
    and redirects outside the caller's allow-list. Redirects are supported only for
    GET requests; sensitive headers are stripped whenever the host changes.
    """

    normalized_hosts = _normalize_allowed_hosts(allowed_hosts)
    normalized_method = str(method).strip().upper()
    if normalized_method not in {"GET", "POST"}:
        raise SecureHTTPError("Outbound HTTP method is not allowed.")
    if body is not None and not isinstance(body, bytes):
        raise SecureHTTPError("Outbound request body must be bytes.")
    if body is not None and len(body) > max_request_bytes:
        raise SecureHTTPError("Outbound request body exceeds the configured size limit.")
    if max_response_bytes < 1 or max_response_bytes > 32 * 1024 * 1024:
        raise SecureHTTPError("Outbound response size limit is invalid.")
    if max_request_bytes < 1 or max_request_bytes > 16 * 1024 * 1024:
        raise SecureHTTPError("Outbound request size limit is invalid.")
    if max_redirects < 0 or max_redirects > 5:
        raise SecureHTTPError("Outbound redirect limit is invalid.")

    timeout = max(1.0, min(float(timeout_seconds), _MAX_TIMEOUT_SECONDS))
    current_url = url
    current_headers = _validate_headers(headers)
    redirects_remaining = max_redirects
    previous_host: str | None = None

    while True:
        host, target = _validate_url(current_url, normalized_hosts)
        if previous_host is not None and host != previous_host:
            current_headers = {
                name: value
                for name, value in current_headers.items()
                if name.casefold() not in _SENSITIVE_REDIRECT_HEADERS
            }

        connection = http.client.HTTPSConnection(
            host,
            port=443,
            timeout=timeout,
            context=ssl.create_default_context(),
        )
        try:
            connection.request(
                normalized_method,
                target,
                body=body,
                headers=current_headers,
            )
            response = connection.getresponse()
            response_body = _read_bounded_response(response, max_response_bytes)
            response_headers = tuple((str(name), str(value)) for name, value in response.getheaders())
            status = int(response.status)
        except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
            raise SecureHTTPError("Secure outbound HTTPS transport failed.") from exc
        finally:
            connection.close()

        if status not in _REDIRECT_STATUSES:
            return SecureHTTPResponse(
                status=status,
                headers=response_headers,
                body=response_body,
                url=current_url,
            )

        if normalized_method != "GET" or redirects_remaining <= 0:
            return SecureHTTPResponse(
                status=status,
                headers=response_headers,
                body=response_body,
                url=current_url,
            )

        location = next(
            (value for name, value in response_headers if name.casefold() == "location"),
            "",
        ).strip()
        if not location or _contains_control_characters(location):
            raise SecureHTTPError("Remote redirect target is invalid.")

        next_url = urljoin(current_url, location)
        next_host, _ = _validate_url(next_url, normalized_hosts)
        previous_host = host
        current_url = next_url
        redirects_remaining -= 1

        # GET redirects never forward a request body.
        body = None
        if next_host != host:
            current_headers = {
                name: value
                for name, value in current_headers.items()
                if name.casefold() not in _SENSITIVE_REDIRECT_HEADERS
            }
