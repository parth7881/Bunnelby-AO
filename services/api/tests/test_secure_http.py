from __future__ import annotations

import unittest
from unittest.mock import patch

from services.api.app.secure_http import SecureHTTPError, request_https


class _FakeResponse:
    def __init__(self, *, status: int = 200, body: bytes = b"ok", headers=None):
        self.status = status
        self._body = body
        self._headers = list(headers or [])

    def getheader(self, name: str):
        for header_name, value in self._headers:
            if header_name.casefold() == name.casefold():
                return value
        return None

    def getheaders(self):
        return list(self._headers)

    def read(self, amount: int = -1) -> bytes:
        if amount is None or amount < 0:
            return self._body
        return self._body[:amount]


class _FakeConnection:
    responses: list[_FakeResponse] = []
    requests: list[dict] = []
    hosts: list[str] = []

    def __init__(self, host, port=443, timeout=None, context=None):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.context = context
        type(self).hosts.append(host)

    def request(self, method, target, body=None, headers=None):
        type(self).requests.append(
            {
                "host": self.host,
                "method": method,
                "target": target,
                "body": body,
                "headers": dict(headers or {}),
            }
        )

    def getresponse(self):
        if not type(self).responses:
            raise AssertionError("No fake HTTPS response configured")
        return type(self).responses.pop(0)

    def close(self):
        return None


class SecureHTTPTests(unittest.TestCase):
    def setUp(self) -> None:
        _FakeConnection.responses = []
        _FakeConnection.requests = []
        _FakeConnection.hosts = []

    def test_rejects_non_https_before_network_access(self) -> None:
        with patch("services.api.app.secure_http.http.client.HTTPSConnection") as connection:
            with self.assertRaises(SecureHTTPError):
                request_https("http://api.example.com/data", allowed_hosts={"api.example.com"})
            connection.assert_not_called()

    def test_rejects_non_allowlisted_host_credentials_and_custom_port(self) -> None:
        invalid_urls = (
            "https://evil.example/data",
            "https://user:pass@api.example.com/data",
            "https://api.example.com:8443/data",
            "https://api.example.com/data#fragment",
        )
        for value in invalid_urls:
            with self.subTest(value=value):
                with self.assertRaises(SecureHTTPError):
                    request_https(value, allowed_hosts={"api.example.com"})

    def test_rejects_control_characters_and_transport_managed_headers(self) -> None:
        with self.assertRaises(SecureHTTPError):
            request_https("https://api.example.com/a\nb", allowed_hosts={"api.example.com"})
        with self.assertRaises(SecureHTTPError):
            request_https(
                "https://api.example.com/data",
                allowed_hosts={"api.example.com"},
                headers={"Host": "evil.example"},
            )

    @patch("services.api.app.secure_http.http.client.HTTPSConnection", _FakeConnection)
    def test_bounds_response_using_content_length_and_actual_bytes(self) -> None:
        _FakeConnection.responses = [
            _FakeResponse(status=200, body=b"x", headers=[("Content-Length", "99")])
        ]
        with self.assertRaises(SecureHTTPError):
            request_https(
                "https://api.example.com/data",
                allowed_hosts={"api.example.com"},
                max_response_bytes=10,
            )

        _FakeConnection.responses = [_FakeResponse(status=200, body=b"x" * 11)]
        with self.assertRaises(SecureHTTPError):
            request_https(
                "https://api.example.com/data",
                allowed_hosts={"api.example.com"},
                max_response_bytes=10,
            )

    @patch("services.api.app.secure_http.http.client.HTTPSConnection", _FakeConnection)
    def test_allows_bounded_https_request_to_exact_host(self) -> None:
        _FakeConnection.responses = [
            _FakeResponse(status=200, body=b'{"ok":true}', headers=[("Content-Type", "application/json")])
        ]
        result = request_https(
            "https://api.example.com/v1/data?limit=1",
            allowed_hosts={"api.example.com"},
            headers={"Accept": "application/json"},
            max_response_bytes=1024,
        )
        self.assertEqual(result.status, 200)
        self.assertEqual(result.body, b'{"ok":true}')
        self.assertEqual(_FakeConnection.requests[0]["target"], "/v1/data?limit=1")
        self.assertEqual(_FakeConnection.requests[0]["host"], "api.example.com")

    @patch("services.api.app.secure_http.http.client.HTTPSConnection", _FakeConnection)
    def test_cross_host_redirect_requires_allowlist_and_strips_sensitive_headers(self) -> None:
        _FakeConnection.responses = [
            _FakeResponse(
                status=302,
                headers=[("Location", "https://assets.example.com/model.bin")],
            ),
            _FakeResponse(status=200, body=b"model"),
        ]
        result = request_https(
            "https://downloads.example.com/model.bin",
            allowed_hosts={"downloads.example.com", "assets.example.com"},
            headers={"Authorization": "Bearer secret", "Accept": "application/octet-stream"},
            max_redirects=1,
        )
        self.assertEqual(result.body, b"model")
        self.assertEqual(len(_FakeConnection.requests), 2)
        self.assertIn("Authorization", _FakeConnection.requests[0]["headers"])
        self.assertNotIn("Authorization", _FakeConnection.requests[1]["headers"])
        self.assertEqual(_FakeConnection.requests[1]["host"], "assets.example.com")

    @patch("services.api.app.secure_http.http.client.HTTPSConnection", _FakeConnection)
    def test_redirect_to_unapproved_host_fails_closed(self) -> None:
        _FakeConnection.responses = [
            _FakeResponse(status=302, headers=[("Location", "https://evil.example/model.bin")])
        ]
        with self.assertRaises(SecureHTTPError):
            request_https(
                "https://downloads.example.com/model.bin",
                allowed_hosts={"downloads.example.com"},
                max_redirects=1,
            )
        self.assertEqual(len(_FakeConnection.requests), 1)


if __name__ == "__main__":
    unittest.main()
